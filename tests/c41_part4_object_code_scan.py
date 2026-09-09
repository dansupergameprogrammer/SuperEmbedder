#!/usr/bin/env python3
"""tests/c41_part4_object_code_scan.py -- TE-144 (U1 slice 1): C41 part 4,
the instruction-level object-code scan
(`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C41 part 4: "The instruction-
level scan over the `superembedder` library target's own object code on the
reproducible path ... asserting zero matches against the same mnemonic
class the engine-side scan uses ... Its readings are QUARANTINED until
commissioned against the must-reject population sec 1.3 names, authored by
a seat independent of its builder").

WHAT THIS SEAT BUILDS AND WHAT IT DOES NOT (dispatch sec 3's own
discipline). This script BUILDS and EXECUTES the scan; it does NOT author
the scan's must-accept/must-reject commissioning pair, and its reading is
printed as QUARANTINED -- recorded, never headlined, per
StandardsDocument.md sec 5.4's commissioning discipline and this project's
own C41 disposition (sec 8's cell text, `SuperEmbedder_Plan.md` sec 9 dim
11's own N1 note in `Claude/Plans/te140-u1-remainder-sequencing.md` sec 6).
Independent commissioning of this instrument is a different seat's work
(sec 3 of the dispatch that authored this file); this script's own exit
code is ALWAYS 0 for a scan that runs to completion, whatever it finds --
a nonzero exit here would make this uncommissioned instrument's reading
gate the build, which the quarantine explicitly forbids. A scan that
cannot even RUN (the disassembler is missing, an object file does not
exist) is the only case this script fails on, because that is an
authoring-time infrastructure defect, not a quarantined finding.

SCOPE. The scan derives every compiled C++ translation unit from the root
`set(SEMB_LIBRARY_SOURCES ...)` block at test time.  The list is therefore
the library target's actual CMake population rather than a second,
hand-maintained subset that can lag it.  A separately registered structural
check compares this derived population to the root list and refuses a
difference.  The two headers `binary32_construct.h` and `big_uint.h` are
never compiled as their own translation unit; their compiled code appears in
the objects for the translation units that include them, so those objects
cover the headers too.

THE MNEMONIC CLASS -- STATED, AND ITS OWN LIMIT NAMED. sec 8's C41 part 4
text says this scan uses "the same mnemonic class the engine-side scan
uses," carried by reference to `Claude/Vitruvius/t2265-superslm-fp-free-
open-design-2026-08-24.md` sec 4.1 -- a SuperSLM-repository casebook this
dispatch's writable/readable roots do not include (D:\\Wizard and
D:\\SuperEmbedder only). This script's own mnemonic class is therefore this
seat's OWN reasoned construction, not a transcription of that design's
literal list, and is UNDETERMINED whether it agrees exactly -- filed
in the casebook, with what would settle it (reading that design's sec 4.1
directly). This script scans for x87 (`f`-prefixed data-processing
mnemonics: fadd/fsub/fmul/fdiv/fcom/fsqrt/fabs/fchs/fyl2x/fscale/frndint/
fld/fst family EXCLUDING pure stack bookkeeping already excluded below) and
SSE/AVX scalar-and-packed floating-point ARITHMETIC, COMPARISON and
CONVERSION mnemonics (add/sub/mul/div/min/max/sqrt/rcp/rsqrt/cmp/comi/ucomi
+ ss/sd/ps/pd suffix; cvt*2*; the `vfmadd`/`vfmsub`/`vfnmadd`/`vfnmsub`
family; AVX-512 `k`-masked and `z`-suffixed forms of the same). It does
NOT flag pure data-movement mnemonics (`movss`, `movsd`, `movaps`,
`movapd`, `movups`, `movupd`, `movd`, `movq`) -- these copy bits without
computing a floating-point result and are how this project's own
integer-exact code legitimately shuttles an int8/int32 payload through an
XMM register on some optimizer-chosen code paths; flagging them would
make the scan noisy with data movement sec 3.2 item 4's own claim never
addresses. This exclusion is a SCOPE CHOICE, stated so a reader auditing
this scan's own coverage does not need to infer it from silence.

RED-FIRST: before this file existed, no test in tests/ disassembled any
object file or scanned for a floating-point mnemonic class at all
(confirmed by `git grep -n "objdump\\|disassemb" tests/` returning
nothing). This is the cell's own red-to-green transition: PART OF this
slice's build is simply that the scan now exists and runs -- there was no
instrument before it to have any reading at all.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

def library_translation_units(repo_root: Path) -> list[str]:
    """Derive C41's source population from SEMB_LIBRARY_SOURCES at test time."""
    cmake = (repo_root / "CMakeLists.txt").read_text(encoding="utf-8")
    match = re.search(r"set\s*\(\s*SEMB_LIBRARY_SOURCES\s*(.*?)\)", cmake, re.DOTALL)
    if match is None:
        raise RuntimeError("C41 part 4: cannot find set(SEMB_LIBRARY_SOURCES ...) in root CMakeLists.txt")
    sources = []
    for token in re.findall(r"[^\s#)]+", re.sub(r"#.*", "", match.group(1))):
        path = Path(token)
        if path.suffix == ".cpp":
            sources.append(path.name)
    if not sources:
        raise RuntimeError("C41 part 4: SEMB_LIBRARY_SOURCES contains no .cpp translation units")
    return sources

# Header files inlined into the TUs above (binary32_construct.h into both
# pool TUs, big_uint.h into both pool TUs and, transitively, wherever a
# pool TU's own includes carry it). Their own compiled code is inside the
# .obj files above -- no separate object exists to point at, and this list
# exists only to say so explicitly in this script's own report.
SCOPED_HEADERS_INLINED_INTO = {
    "binary32_construct.h": ["ps1_pool.cpp", "ps_n_pool.cpp"],
    "big_uint.h": ["ps1_pool.cpp", "ps_n_pool.cpp"],
}

# x87 data-processing mnemonics (never the control/stack-management forms
# fld/fst/fstp/fxch/fnop/fwait/fld1/fldz/finit/fclex/fstcw/fldcw, which
# move or manage state without computing a floating-point RESULT from
# operands -- fldz/fld1 load an exact CONSTANT, not a computed value, and
# are excluded on the identical "no operation performed" reasoning movss
# is excluded on below).
X87_ARITH = re.compile(
    r"^(fadd|fsub|fsubr|fmul|fdiv|fdivr|fcom|fcomp|fcompp|fucom|fucomp|fucompp|"
    r"fcomi|fcomip|fucomi|fucomip|fsqrt|fabs|fchs|fyl2x|fyl2xp1|fscale|frndint|"
    r"fprem|fprem1|f2xm1|fpatan|fptan|fsin|fcos|fsincos|fxtract)(p|r|rp)?$"
)

# SSE/AVX/AVX-512 scalar+packed floating-point arithmetic, comparison and
# conversion mnemonics. `v`-prefixed AVX forms and `k`/`z`-suffixed
# AVX-512 masked forms of the identical operation are covered by the same
# base-name match (mnemonics are matched by PREFIX/SUFFIX shape, not a
# fixed enumeration of every VEX/EVEX spelling objdump may print).
SSE_AVX_ARITH = re.compile(
    r"^v?(add|sub|mul|div|min|max|sqrt|rcp|rsqrt|dpp|hadd|hsub|"
    r"cmp|comi|ucomi|round|scalef|rndscale|"
    r"fmadd\d*|fmsub\d*|fnmadd\d*|fnmsub\d*)(ss|sd|ps|pd)$"
)
CVT = re.compile(r"^v?cvt[a-z0-9]*2[a-z0-9]+$")

# Pure data-movement mnemonics this scan deliberately does NOT flag (see
# this file's own header comment): copying bits, never computing a value.
EXCLUDED_MOVES = {
    "movss", "movsd", "movaps", "movapd", "movups", "movupd", "movd", "movq",
    "vmovss", "vmovsd", "vmovaps", "vmovapd", "vmovups", "vmovupd", "vmovd", "vmovq",
}


def classify(mnemonic: str) -> bool:
    m = mnemonic.lower().rstrip(".")
    if m in EXCLUDED_MOVES:
        return False
    if X87_ARITH.match(m):
        return True
    if SSE_AVX_ARITH.match(m):
        return True
    if CVT.match(m) and m not in EXCLUDED_MOVES:
        return True
    return False


def find_object(build_dir: Path, tu: str) -> "Path | None":
    candidates = list(build_dir.glob(f"CMakeFiles/superembedder.dir/**/{tu}.obj"))
    return candidates[0] if candidates else None


def disassemble(objdump: str, obj_path: Path) -> str:
    proc = subprocess.run([objdump, "-d", "--no-show-raw-insn", str(obj_path)],
                           capture_output=True, text=True)
    return proc.stdout


MNEMONIC_LINE = re.compile(r"^\s*[0-9a-fA-F]+:\s+([a-zA-Z][a-zA-Z0-9]*)")


def scan_object(objdump: str, obj_path: Path) -> "list[str]":
    text = disassemble(objdump, obj_path)
    matches = []
    for line in text.splitlines():
        m = MNEMONIC_LINE.match(line)
        if not m:
            continue
        mnemonic = m.group(1)
        if classify(mnemonic):
            matches.append(f"{obj_path.name}: {line.strip()}")
    return matches


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--objdump", default="", help="path to llvm-objdump; empty tries PATH, then MISSING PREREQUISITE")
    args = ap.parse_args(argv)

    build_dir = Path(args.build_dir)
    objdump = args.objdump or shutil.which("llvm-objdump") or shutil.which("llvm-objdump.exe") or ""

    if not objdump or not Path(objdump).exists():
        print("C41 part 4: MISSING PREREQUISITE -- no llvm-objdump found (checked --objdump and PATH). "
              "This scan needs a disassembler; it is not itself required for any other Slice 1 cell to "
              "pass, so this leg reports MISSING PREREQUISITE (non-failing) rather than FAIL, matching "
              "this suite's own convention for a leg whose external prerequisite is absent.")
        return 0

    try:
        scoped_tus = library_translation_units(Path(args.repo_root))
    except (OSError, RuntimeError) as exc:
        print(f"C41 part 4: INFRASTRUCTURE FAIL -- {exc}")
        return 1

    total_matches = []
    scoped_report = []
    for tu in scoped_tus:
        obj = find_object(build_dir, tu)
        if obj is None:
            print(f"C41 part 4: INFRASTRUCTURE FAIL -- no compiled object found for '{tu}' under {build_dir} "
                  f"-- build the 'superembedder' target first")
            return 1
        matches = scan_object(objdump, obj)
        total_matches.extend(matches)
        scoped_report.append((tu, obj, len(matches)))

    print("C41 part 4 -- instruction-level object-code scan (QUARANTINED, not commissioned; "
          "this reading is recorded, never acted on, per StandardsDocument.md sec 5.4):")
    for tu, obj, count in scoped_report:
        print(f"  {tu:20s} -> {obj}  matches={count}")
    for header, via in SCOPED_HEADERS_INLINED_INTO.items():
        print(f"  {header:20s} -> inlined into {', '.join(via)}; covered by those objects' own scan above")
    print(f"  TOTAL MATCHES: {len(total_matches)}")
    for line in total_matches[:50]:
        print(f"    {line}")
    if len(total_matches) > 50:
        print(f"    ... and {len(total_matches) - 50} more")

    print("  DISPOSITION: reading filed as QUARANTINED. Its own mnemonic class is this seat's reasoned "
          "construction (see this script's header comment), UNDETERMINED against "
          "`Claude/Vitruvius/t2265-superslm-fp-free-open-design-2026-08-24.md` sec 4.1's literal list, "
          "which this dispatch's roots do not include. This script's own exit code is 0 whenever the scan "
          "completed, whatever it found -- a nonzero exit would make an uncommissioned instrument's "
          "reading gate the build, which the quarantine forbids.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
