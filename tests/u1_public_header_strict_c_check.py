"""tests/u1_public_header_strict_c_check.py -- TE-94 (D-SLM6314 resolution,
sec 7.1; K-16): the strict-C compile cell for the public header, with its
own must-accept and must-reject.

WHAT IT PROVES. `include/superembedder/semb.h` is a C ABI header (plan sec 3.1),
so it must compile as strict C on every toolchain that builds the library --
MSVC and clang-cl under `/TC /W4 /WX`, GCC/Clang/AppleClang under
`-std=c99 -Wall -Wextra -Werror -pedantic`. At `496d036` that compile was run
by hand once and recorded; it was not a cell (planner record sec 10.4). The
object library `u1_public_header_strict_c` in tests/CMakeLists.txt makes it a
BUILD-time cell on every platform; this script is the ctest-time cell that
proves the compile can FAIL BY NAME when C++ syntax enters the header.

THE CONSTRUCTIONS.
  S-1 must-accept: tests/u1_public_header_strict_c.c compiles against the real
      header under the strict-C flags.
  S-2 must-reject: for each C++-only construct below, a mutated copy of the
      header carrying it is compiled under the same flags and MUST FAIL --
      reported as SEMB_PUBLIC_HEADER_NOT_STRICT_C(<construct>) when it does
      not. Each mutant is ALSO compiled as C++ and must SUCCEED there, which
      is what proves the cell discriminates C from C++ rather than rejecting
      garbage: a mutant that fails both ways would prove nothing about the
      C mode.

USAGE (as tests/CMakeLists.txt registers it):
  python tests/u1_public_header_strict_c_check.py --c-compiler <path> --cxx-compiler <path>
      --compiler-id <MSVC|Clang|GNU|AppleClang> [--frontend <MSVC|GNU>]
      --include-dir <repo>/include --scratch <dir>

Exit codes: 0 every construction behaved; 1 otherwise.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "u1_public_header_strict_c.c"
HEADER_REL = Path("superembedder") / "semb.h"

# Each mutant: a label, and the C++-only line injected just before the header's
# closing include-guard #endif (outside the extern "C" block, inside the guard).
MUTANTS = [
    ("class-forward-declaration", "class semb_cpp_only_class;"),
    ("bool-parameter", "int semb_cpp_only_bool(bool flag);"),
    ("default-argument", "int semb_cpp_only_default(int value = 0);"),
    ("nullptr-initializer", "static const void* const semb_cpp_only_nullptr = nullptr;"),
    ("reference-parameter", "int semb_cpp_only_reference(const semb_config& cfg);"),
    ("unguarded-extern-c", 'extern "C" int semb_cpp_only_linkage(void);'),
    ("namespace", "namespace semb_cpp_only_ns { }"),
]


def msvc_frontend(compiler_id: str, frontend: str) -> bool:
    return compiler_id == "MSVC" or frontend == "MSVC"


def compile_once(compiler: str, msvc_like: bool, as_cxx: bool, include_dir: Path, source: Path, out: Path):
    """Runs one compile-only invocation; returns (returncode, combined output)."""
    if msvc_like:
        lang = "/TP" if as_cxx else "/TC"
        cmd = [compiler, "/nologo", lang, "/W4", "/WX", "/c", f"/I{include_dir}", f"/Fo{out}", str(source)]
    else:
        if as_cxx:
            cmd = [compiler, "-x", "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-c",
                   f"-I{include_dir}", str(source), "-o", str(out)]
        else:
            cmd = [compiler, "-x", "c", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c",
                   f"-I{include_dir}", str(source), "-o", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--c-compiler", required=True)
    ap.add_argument("--cxx-compiler", required=True)
    ap.add_argument("--compiler-id", required=True)
    ap.add_argument("--frontend", default="")
    ap.add_argument("--include-dir", default=str(REPO_ROOT / "include"))
    ap.add_argument("--scratch", required=True)
    args = ap.parse_args(argv)

    include_dir = Path(args.include_dir)
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    msvc_like = msvc_frontend(args.compiler_id, args.frontend)
    failures = 0

    def verdict(ok: bool, item: str, observed: str) -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {item}: {observed}")
        sys.stdout.flush()

    real_header = include_dir / HEADER_REL
    if not real_header.exists():
        print(f"[RED-UNIMPLEMENTED] S-0 the public header exists: {real_header} does not exist")
        return 1
    obj_suffix = ".obj" if msvc_like else ".o"

    # S-1 must-accept.
    rc, out = compile_once(args.c_compiler, msvc_like, False, include_dir, PROBE, scratch / ("probe" + obj_suffix))
    verdict(rc == 0, f"S-1 must-accept: the public header compiles as strict C ({args.compiler_id}{'/' + args.frontend if args.frontend else ''})",
            "exit 0" if rc == 0 else f"SEMB_PUBLIC_HEADER_NOT_STRICT_C: exit {rc}\n{out[-1500:]}")

    # S-2 must-rejects: a mutated header copy under a scratch include root that
    # shadows the real one.
    header_text = real_header.read_text(encoding="utf-8")
    guard_end = header_text.rstrip().rfind("#endif")
    if guard_end < 0:
        verdict(False, "S-2 (setup) the header ends with its include guard's #endif", "no #endif found")
        return 1
    for label, line in MUTANTS:
        mutant_root = scratch / f"mutant-{label}"
        mutant_dir = mutant_root / HEADER_REL.parent
        mutant_dir.mkdir(parents=True, exist_ok=True)
        mutated = header_text[:guard_end] + line + "\n" + header_text[guard_end:]
        (mutant_dir / HEADER_REL.name).write_text(mutated, encoding="utf-8")
        rc_c, out_c = compile_once(args.c_compiler, msvc_like, False, mutant_root, PROBE, mutant_root / ("c" + obj_suffix))
        rc_cxx, out_cxx = compile_once(args.cxx_compiler, msvc_like, True, mutant_root, PROBE, mutant_root / ("cxx" + obj_suffix))
        verdict(rc_c != 0, f"S-2 must-reject [{label}]: the mutated header FAILS to compile as strict C",
                f"exit {rc_c}" if rc_c != 0 else f"SEMB_PUBLIC_HEADER_NOT_STRICT_C({label}): the C compile ACCEPTED C++ syntax")
        verdict(rc_cxx == 0, f"S-2 control [{label}]: the same mutated header compiles as C++ (the cell discriminates C from C++, not garbage)",
                "exit 0" if rc_cxx == 0 else f"exit {rc_cxx}\n{out_cxx[-800:]}")
        if rc_c == 0:
            print(out_c[-800:])

    print(f"\nu1_public_header_strict_c_check: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
