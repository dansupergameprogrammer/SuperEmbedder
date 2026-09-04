"""tests/c14_build_config_target_list_check.py -- TE-80: the owed assertion
for TE-76 review F-4 (Significant), named in the builder's own build log
(`Claude/Brunel/te79-u0b-product-fixes-2026-09-02.md` sec 9 item 2):
`cmake/BuildFlags.cmake`'s `semb_assert_precise_fp()` moved to AFTER
`add_subdirectory(tests)` so its recursive target enumeration actually
covers the test subtree -- this checks the FIX HOLDS by content, not by
"some non-empty list was printed."

WHAT F-4 WAS. `semb_assert_precise_fp()` was called BEFORE
`add_subdirectory(tests)`, so its `SUBDIRECTORIES`-recursing target walk
(`cmake/BuildFlags.cmake`) saw an empty list at call time and the
assertion's own printed "[target;target;...]" set never contained any of
the nine test targets -- C14's own canary TU included, the one target this
whole cell exists to guard. **This is a records/prose distinction as much
as a code one**: a check that merely confirms the assertion PRINTS a
non-empty bracketed list would have passed both before and after the fix
(the pre-fix list was `[superembedder;semb;semb_witness]` -- non-empty,
just incomplete). The obligation, stated exactly by the builder's own
brief text this file is named for, is CONTENT: the printed list must name
a REAL test target.

MECHANISM. `semb_assert_precise_fp()`'s own `message(STATUS ...)` text is
not retained anywhere CMake persists between runs (not in CMakeCache.txt,
not in a generated file) -- the only way to read it is to re-run a real
`cmake -S -B` configure and capture its own stdout, which is exactly what
this check does: a FRESH, throwaway configure of the real, UNMODIFIED
source tree (no scratch copy needed -- nothing here is patched), grepping
the captured configure output for the C14 assertion's own status line and
asserting it contains `c1_ps1_reference_test` (chosen because it is
alphabetically first among the test targets and therefore the one most
likely to be silently dropped by an off-by-one in a future re-ordering).

COMMISSIONED BEFORE TRUSTED: this check is first run against a
DELIBERATELY TRUNCATED copy of the captured configure output (the pre-fix
shape, `[superembedder;semb;semb_witness]`, constructed in memory -- never
written to any tracked file) and must report FAIL; only then is the real,
freshly-captured configure output graded.

USAGE: `python tests/c14_build_config_target_list_check.py [--build-dir
<scratch build dir>]`. Exit 0 only if the commissioning fires correctly
AND the real configure's own printed target list contains a real test
target name.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PREFIX = REPO_ROOT / "build" / "_engine_install"
NINJA_EXECUTABLE = "ninja"
PYTHON_EXECUTABLE = sys.executable
CXX_COMPILER = ""
RC_COMPILER = ""
MT_EXECUTABLE = ""

# The target this check requires to appear in the assertion's own printed
# list -- chosen as stated in the module docstring.
REQUIRED_TARGET = "c1_ps1_reference_test"

# The exact shape of the DEFECTIVE (pre-F-4) printed list, reconstructed
# from the TE-76 review's own quoted execution
# (Claude/Poirot/c24a06e-te76-u0b-review.md F-4:
# "[superembedder;semb;semb_witness] each carry /fp:precise") -- used ONLY
# as a commissioning construction, never written to any file.
DEFECTIVE_LIST_LINE = (
    "-- C14 build-configuration assertion: directory default carries /fp:precise; "
    "no CMAKE_CXX_FLAGS* variable carries /fp:fast; "
    "[superembedder;semb;semb_witness] each carry /fp:precise and no override of it"
)


def extract_target_list_line(configure_output: str) -> str:
    """The one line semb_assert_precise_fp() prints, or '' if not found."""
    for line in configure_output.splitlines():
        if "C14 build-configuration assertion" in line and "each carry" in line:
            return line
    return ""


def line_names_target(line: str, target: str) -> bool:
    m = re.search(r"\[([^\]]*)\]", line)
    if not m:
        return False
    names = [n.strip() for n in m.group(1).split(";")]
    return target in names


def find_cmake() -> str:
    found = shutil.which("cmake")
    if found:
        return found
    candidate = Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/"
                      "CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("no cmake executable found")


def run_fresh_configure(build_dir: Path) -> str:
    """A genuine, throwaway `cmake -S -B` of the REAL, unmodified source
    tree -- nothing patched, nothing copied; this is the actual project,
    configured into a scratch build directory this check owns."""
    cmake = find_cmake()
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    result = subprocess.run(
        [cmake, "-G", "Ninja", "-S", str(REPO_ROOT), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={ENGINE_PREFIX}",
         f"-DCMAKE_MAKE_PROGRAM={NINJA_EXECUTABLE}",
         f"-DPython3_EXECUTABLE={PYTHON_EXECUTABLE}",
         f"-DCMAKE_CXX_COMPILER={CXX_COMPILER}",
         f"-DCMAKE_RC_COMPILER={RC_COMPILER}",
         f"-DCMAKE_MT={MT_EXECUTABLE}"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"configure failed (rc={result.returncode}):\n"
                           f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    return result.stdout


def main(argv: list) -> int:
    global NINJA_EXECUTABLE, PYTHON_EXECUTABLE, CXX_COMPILER, RC_COMPILER, MT_EXECUTABLE
    # TE-83 (TE-81 review N-6, Minor): the USAGE line below documented
    # [--build-dir <scratch build dir>] while this function never read
    # argv at all -- a document claiming what the code does not deliver
    # (StandardsDocument.md sec 5.6). Implemented for real: an explicit
    # --build-dir overrides the scratch directory the fresh configure
    # below runs into; omitted, it defaults to the same path as before.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", default=None)
    ap.add_argument("--ninja-executable", default="ninja")
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--cxx-compiler", default="")
    ap.add_argument("--rc-compiler", default="")
    ap.add_argument("--mt-executable", default="")
    args = ap.parse_args(argv)
    NINJA_EXECUTABLE = args.ninja_executable
    PYTHON_EXECUTABLE = args.python_executable
    CXX_COMPILER = args.cxx_compiler
    RC_COMPILER = args.rc_compiler
    MT_EXECUTABLE = args.mt_executable

    # Commissioning: the defective (pre-F-4) list must be REJECTED.
    defective_line = extract_target_list_line(DEFECTIVE_LIST_LINE)
    if not defective_line:
        print("SELFTEST FAIL: could not even locate the assertion's own line inside the "
              "constructed defective output.", file=sys.stderr)
        return 1
    if line_names_target(defective_line, REQUIRED_TARGET):
        print(f"SELFTEST FAIL: the constructed DEFECTIVE (pre-F-4) target list was reported as "
              f"containing '{REQUIRED_TARGET}' -- the check cannot fail, which is the same "
              f"defect F-4 itself was.", file=sys.stderr)
        return 1
    print("commissioning: the constructed pre-F-4 target list ([superembedder;semb;"
          "semb_witness]) is correctly rejected -- proceeding to the real configure.")

    # The real thing: a fresh configure of the real tree, graded for real.
    build_dir = (Path(args.build_dir) if args.build_dir else
                 REPO_ROOT / "build" / "_scratch" / "c14_target_list_check")
    try:
        output = run_fresh_configure(build_dir)
    except Exception as ex:  # noqa: BLE001
        print(f"FAIL: could not run a fresh configure: {ex}", file=sys.stderr)
        return 1

    real_line = extract_target_list_line(output)
    if not real_line:
        print("FAIL: the real configure's own output contains no C14 build-configuration "
              "assertion line at all.", file=sys.stderr)
        print(output[-3000:], file=sys.stderr)
        return 1
    print(f"real configure's own printed line: {real_line}")

    if not line_names_target(real_line, REQUIRED_TARGET):
        print(f"FAIL: the real configure's own printed target list does not contain "
              f"'{REQUIRED_TARGET}' -- semb_assert_precise_fp()'s recursive target walk is not "
              f"covering the test subtree (TE-76 review F-4).", file=sys.stderr)
        return 1

    print(f"PASS: the real configure's own printed target list names '{REQUIRED_TARGET}' -- "
          f"F-4 holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
