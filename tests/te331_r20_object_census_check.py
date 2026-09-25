"""tests/te331_r20_object_census_check.py -- TE-331 (U2-1/U2-3 red suite): R20's
post-build census, required in 1.0 before a certified toolchain's cell is
listed (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-1 "No certified
object defines a floating-point substitutable function"; sec 10 M19).

THE CLAIM. No certified object file defines a floating-point substitutable
function -- an external COMDAT whose selection is not "no duplicates" (a
header-inline function or a template instantiation the linker may fold
against another translation unit's copy) that does floating-point
arithmetic, comparison, conversion or FMA. Where one exists, a monolithic
consumer's static link can substitute a differently-compiled copy under the
certified fingerprint (F34/F38's class), and R20 closes it at the source by
moving the container instantiations that host it to ordered containers with
no floating-point member function.

THE READER, ported unchanged in method from the plan's own probes
(`Claude/Vitruvius/te311-probe/te311_comdat.py`'s `substitutable`/
`disasm_by_section`/`is_fp`, reused at TE-323/TE-321 as
`Claude/Vitruvius/te323-probe/msvc_object_census.py` and
`Claude/Vitruvius/te321-probe/te321_census.py`'s GCC analogue): for every
object the certified static archive contains (never the product's own
LINKED IMAGE -- TE-322's strike found a linked PE/EXE carries no COFF
symbol table at all, and GNU ld demotes every HIDDEN vague-linkage symbol
from WEAK to LOCAL in its own link, so a census over either linked image
reads a resolved population, not the one a CONSUMER's separate static link
resolves against), extract every substitutable external function
(MSVC/COFF: a COMDAT selection that is not IMAGE_COMDAT_SELECT_NODUPLICATES
(1) or IMAGE_COMDAT_SELECT_ASSOCIATIVE (5); GCC/ELF: a WEAK-bound,
non-undefined FUNC symbol -- GCC's own vague-linkage form) and classify its
disassembly floating-point-computing by instruction mnemonic (SSE/AVX
scalar and packed arithmetic, comparison, conversion, FMA; x87), never by
source-level reasoning about what the function "does".

WHY THIS IS RED TODAY, ON THIS EXACT TREE (`fca421b`, four commits ahead of
the plan's own grounding pin `c8d4147`, none of which touch `src/` per
`git log --oneline c8d4147..fca421b -- src/`): the fix (moving five
container instantiations -- the three handle registries and the two
duplicate-id sets in encoder.cpp/query.cpp/bank.cpp -- to std::map/std::set,
which are FP-free) is NOT IN THIS TREE. It exists only as a scratch,
never-committed source tree at TE-323's own probe (D:/_te323/src-fixed,
per the plan's handoff: "its only existing form is a source tree ...
never committed to D:\\SuperEmbedder"). So this census, run against a real
build of the real, unfixed source, reads the real defect: a nonzero
floating-point-computing count on the certified toolchain(s) this cell can
reach. It reads ZERO only once the five sites move -- the must-accept below
-- which is Brunel's to build, not this seat's.

USAGE (MSVC/COFF leg):
    python tests/te331_r20_object_census_check.py msvc \
        --lib build/msvc/superembedder.lib --dumpbin <path or on PATH> \
        --libexe <path or on PATH>

USAGE (GCC/ELF leg, run under `wsl -d Ubuntu-24.04 -u root --`):
    python3 tests/te331_r20_object_census_check.py gcc \
        --archive build/gcc/libsuperembedder.a

Exit 0 only when the census reads exactly zero FP-computing substitutable
functions (the must-accept shape); exit 1 (RED, naming every offender) on
any nonzero reading, a missing archive, or a missing tool -- so "the tool
isn't on PATH" and "the census found a real defect" are both failures, never
silently skipped.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Shared classifier: which mnemonics are floating-point-computing. Ported
# verbatim (same regexes) from te311_comdat.py's own `is_fp`, the reader the
# plan's own R20 text and TE-322/TE-323's executed censuses use.
# ---------------------------------------------------------------------------
FP_SSE = re.compile(r"^v?(add|sub|mul|div|sqrt|min|max|rcp|rsqrt|round|hadd|hsub|addsub|dp|cmp[a-z]*|u?comi|"
                    r"getexp|getmant|scalef|reduce|range|fixupimm)(ss|sd|ps|pd|sh|ph)$")
FP_CVT = re.compile(r"^v?cvt[a-z0-9]*$")
FP_FMA = re.compile(r"^vf(n)?m(add|sub|addsub|subadd)[0-9]+(ss|sd|ps|pd)$")
X87 = re.compile(r"^f(?!nop|wait|xsave|xrstor|emms)[a-z0-9]+$")


def is_fp(mnemonic: str) -> bool:
    m = mnemonic.lower()
    return bool(FP_SSE.match(m) or FP_CVT.match(m) or FP_FMA.match(m) or X87.match(m))


# ---------------------------------------------------------------------------
# MSVC / COFF leg
# ---------------------------------------------------------------------------
SYM = re.compile(r"^([0-9A-F]{3,}) [0-9A-F]{8} (SECT[0-9A-F]+)\s+\w+\s+(\(\))?\s+(External|Static)\s+\| (\S+)")
AUX = re.compile(r"selection\s+(\d)")
HDR = re.compile(r"^SECTION HEADER #([0-9A-F]+)$")
INS = re.compile(r"^  ([0-9A-F]{16}): (\S+)")


def _msvc_substitutable(dumpbin: str, obj: Path) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    txt = subprocess.run([dumpbin, "/nologo", "/symbols", str(obj)], capture_output=True, text=True).stdout
    selection: Dict[str, int] = {}
    funcs, data = [], []
    lines = txt.splitlines()
    for i, ln in enumerate(lines):
        m = SYM.match(ln)
        if not m:
            continue
        sect, isfn, storage, name = m.group(2), m.group(3), m.group(4), m.group(5)
        if storage == "Static" and name.startswith("."):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            a = AUX.search(nxt)
            if a:
                selection[sect] = int(a.group(1))
            continue
        if storage == "External":
            sel = selection.get(sect)
            if sel is None or sel in (1, 5):
                continue
            (funcs if isfn else data).append((name, int(sect[4:], 16)))
    return funcs, data


def _msvc_code_sections(dumpbin: str, obj: Path) -> List[Tuple[int, int]]:
    txt = subprocess.run([dumpbin, "/nologo", "/headers", str(obj)], capture_output=True, text=True).stdout
    out, cur, size, code = [], None, 0, False
    for ln in txt.splitlines() + ["SECTION HEADER #FFFF"]:
        m = HDR.match(ln.strip())
        if m:
            if cur is not None and code and size > 0:
                out.append((cur, size))
            cur, size, code = int(m.group(1), 16), 0, False
            continue
        s = ln.strip()
        if s.endswith("size of raw data"):
            size = int(s.split()[0], 16)
        elif s == "Code":
            code = True
    return out


def _msvc_disasm_by_section(dumpbin: str, obj: Path) -> Dict[int, List[str]]:
    txt = subprocess.run([dumpbin, "/nologo", "/disasm:nobytes", str(obj)], capture_output=True, text=True).stdout
    txt = txt.split("\n  Summary")[0]
    blocks, cur, last = [], None, -1
    for ln in txt.splitlines():
        m = INS.match(ln)
        if not m:
            continue
        addr = int(m.group(1), 16)
        if addr == 0 or addr <= last:
            cur = {"mn": [], "last": 0}
            blocks.append(cur)
        cur["mn"].append(m.group(2))
        cur["last"] = addr
        last = addr
    secs = _msvc_code_sections(dumpbin, obj)
    if len(secs) != len(blocks):
        raise RuntimeError(f"{obj.name}: {len(blocks)} disassembly blocks against {len(secs)} code sections")
    for (sec, size), b in zip(secs, blocks):
        if b["last"] >= size:
            raise RuntimeError(f"{obj.name}: section {sec} block ends at {b['last']:#x}, size {size:#x}")
    return {sec: b["mn"] for (sec, _), b in zip(secs, blocks)}


def census_msvc(lib: Path, dumpbin: str, libexe: str) -> int:
    if not lib.exists():
        print(f"RED-UNIMPLEMENTED: {lib} does not exist -- build the superembedder target first")
        return 1
    with tempfile.TemporaryDirectory(prefix="te331_r20_msvc_") as td:
        outdir = Path(td)
        members_txt = subprocess.run([libexe, "/nologo", "/list", str(lib)], capture_output=True, text=True).stdout
        members = members_txt.split()
        objs = []
        for m in members:
            dst = outdir / Path(m.replace("\\", "/")).name
            subprocess.run([libexe, "/nologo", f"/extract:{m}", f"/out:{dst}", str(lib)],
                           check=True, capture_output=True)
            objs.append(dst)
        total, fp = 0, []
        for o in objs:
            funcs, _ = _msvc_substitutable(dumpbin, o)
            dis = _msvc_disasm_by_section(dumpbin, o) if funcs else {}
            for f, sec in funcs:
                total += 1
                mnems = sorted({x for x in dis.get(sec, []) if is_fp(x)})
                if mnems:
                    fp.append((o.name, f, mnems))
        print(f"[R20/M19 MSVC/COFF census] {lib}")
        print(f"  objects: {len(objs)}; substitutable external functions: {total}; FP-computing: {len(fp)}")
        for o, f, mnems in fp:
            print(f"   FP  {o:24s} {f[:110]:110s} {','.join(mnems)[:60]}")
        if fp:
            print(f"RED (R20 must-accept unmet): {len(fp)} of {total} substitutable definitions are "
                  f"floating-point-computing on the real, unfixed archive -- exactly the population U2-1's "
                  f"post-build census must refuse. GREEN once the five container instantiations named in "
                  f"the plan (encoder.cpp/query.cpp/bank.cpp's handle registries and duplicate-id sets) move "
                  f"to std::map/std::set with no floating-point member function.")
            return 1
        print("PASS (0 of {} FP-computing) -- R20's must-accept".format(total))
        return 0


# ---------------------------------------------------------------------------
# GCC / ELF leg (run under WSL against a real Ubuntu-24.04 GCC 13.3.0 build)
# ---------------------------------------------------------------------------
def _gcc_members(ar: str, archive: Path) -> List[str]:
    out = subprocess.run([ar, "t", str(archive)], capture_output=True, text=True, check=True).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _gcc_weak_funcs(readelf: str, obj: Path) -> List[str]:
    out = subprocess.run([readelf, "-sW", str(obj)], capture_output=True, text=True, check=True).stdout
    names = []
    for ln in out.splitlines():
        parts = ln.split()
        # Num: Value Size Type Bind Vis Ndx Name
        if len(parts) < 8:
            continue
        typ, bind, ndx = parts[3], parts[4], parts[6]
        if typ == "FUNC" and bind == "WEAK" and ndx != "UND":
            names.append(parts[7])
    return names


def _gcc_disasm(objdump: str, obj: Path, func: str) -> List[str]:
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", str(obj)], capture_output=True, text=True,
                         check=True).stdout
    mnems: List[str] = []
    in_func = False
    marker = f"<{func}>:"
    for ln in out.splitlines():
        if marker in ln:
            in_func = True
            continue
        if in_func:
            if ln.strip() == "" :
                break
            m = re.match(r"^\s*[0-9a-f]+:\s*([a-zA-Z0-9\.]+)", ln)
            if m:
                mnems.append(m.group(1))
    return mnems


def census_gcc(archive: Path, ar: str, readelf: str, objdump: str) -> int:
    if not archive.exists():
        print(f"RED-UNIMPLEMENTED: {archive} does not exist -- build the certified GCC 13.3.0/WSL member first")
        return 1
    with tempfile.TemporaryDirectory(prefix="te331_r20_gcc_") as td:
        outdir = Path(td)
        members = _gcc_members(ar, archive)
        total, fp = 0, []
        for m in members:
            obj = outdir / m
            subprocess.run([ar, "x", f"--output={outdir}", str(archive), m], check=True, capture_output=True)
            funcs = _gcc_weak_funcs(readelf, obj)
            for f in funcs:
                total += 1
                mnems = sorted({x for x in _gcc_disasm(objdump, obj, f) if is_fp(x)})
                if mnems:
                    fp.append((m, f, mnems))
        print(f"[R20/M19 GCC/ELF census] {archive}")
        print(f"  objects: {len(members)}; WEAK-bound FUNC candidates: {total}; FP-computing: {len(fp)}")
        for o, f, mnems in fp:
            print(f"   FP  {o:24s} {f[:110]:110s} {','.join(mnems)[:60]}")
        if fp:
            print(f"RED (R20 must-accept unmet): {len(fp)} of {total} WEAK-bound candidates are "
                  f"floating-point-computing on the real, unfixed certified GCC 13.3.0/WSL archive.")
            return 1
        print("PASS (0 of {} FP-computing) -- R20's must-accept".format(total))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="leg", required=True)
    p_msvc = sub.add_parser("msvc")
    p_msvc.add_argument("--lib", required=True, type=Path)
    p_msvc.add_argument("--dumpbin", default="dumpbin")
    p_msvc.add_argument("--libexe", default="lib")
    p_gcc = sub.add_parser("gcc")
    p_gcc.add_argument("--archive", required=True, type=Path)
    p_gcc.add_argument("--ar", default="ar")
    p_gcc.add_argument("--readelf", default="readelf")
    p_gcc.add_argument("--objdump", default="objdump")
    args = ap.parse_args()
    if args.leg == "msvc":
        if shutil.which(args.dumpbin) is None or shutil.which(args.libexe) is None:
            print(f"RED-UNIMPLEMENTED: dumpbin/lib.exe not resolvable ({args.dumpbin}, {args.libexe})")
            return 1
        return census_msvc(args.lib, args.dumpbin, args.libexe)
    if shutil.which(args.ar) is None:
        print(f"RED-UNIMPLEMENTED: binutils not resolvable ({args.ar})")
        return 1
    return census_gcc(args.archive, args.ar, args.readelf, args.objdump)


if __name__ == "__main__":
    sys.exit(main())
