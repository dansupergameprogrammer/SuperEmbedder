"""U1 Slice 7 step 4 (d): C42-derive's two negative configure legs, in C33's
style (TE-264; `Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7 step 4;
D-SLM7206).

CMake compiles `docs/certified-builds.json`'s exact bytes into the library at
configure time and refuses by name when the file is missing or is not
parseable as JSON.  Each leg is a real `cmake -S ... -B ...` against a copy of
the repository with one construction applied, driven through
tools/ci/run_configure_matrix.py's own helpers (`copy_repo`,
`run_cmake_configure`, `record`) so the legs configure exactly as C33's do:

  C42-derive (missing)      the copy carries no docs/certified-builds.json
                            -> configure fails naming SEMB_CERTIFIED_BUILDS_MISSING
  C42-derive (unparseable)  the copy's docs/certified-builds.json is not JSON
                            -> configure fails naming SEMB_CERTIFIED_BUILDS_UNPARSEABLE
  C42-derive (must-accept)  the copy with the committed document unchanged
                            -> configure succeeds

The must-accept is what stops a configure that refuses everything from
passing the two refusals.  `copy_repo` copies the committed `docs/` tree
itself (D-SLM7217 (3)), so each leg copies straight from it.

Placement: the plan appends these legs to tools/ci/run_configure_matrix.py
under C42-derive's name.  That file is outside the test author's writable
surface for TE-264, so the legs live here and reuse its helpers; folding them
into the matrix is a move, not a change of construction.

Prints one JSON report (the matrix's own record shape) and exits 0 only if
every leg passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "ci"))
import run_configure_matrix as matrix  # noqa: E402

DOC_RELATIVE = Path("docs") / "certified-builds.json"


def leg_missing() -> None:
    src = matrix.copy_repo(matrix.SCRATCH / "c42d_missing_src")
    (src / DOC_RELATIVE).unlink(missing_ok=True)
    rc, out = matrix.run_cmake_configure(src, matrix.SCRATCH / "c42d_missing_build", matrix.ENGINE_PREFIX)
    matrix.record("C42-derive (missing): no docs/certified-builds.json", "SEMB_CERTIFIED_BUILDS_MISSING", rc, out)


def leg_unparseable() -> None:
    src = matrix.copy_repo(matrix.SCRATCH / "c42d_unparseable_src")
    (src / DOC_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (src / DOC_RELATIVE).write_bytes(b'{ "schemaVersion": 1, "release": ')
    rc, out = matrix.run_cmake_configure(src, matrix.SCRATCH / "c42d_unparseable_build", matrix.ENGINE_PREFIX)
    matrix.record("C42-derive (unparseable): docs/certified-builds.json is not JSON",
                  "SEMB_CERTIFIED_BUILDS_UNPARSEABLE", rc, out)


def leg_must_accept() -> None:
    src = matrix.copy_repo(matrix.SCRATCH / "c42d_accept_src")
    rc, out = matrix.run_cmake_configure(src, matrix.SCRATCH / "c42d_accept_build", matrix.ENGINE_PREFIX)
    matrix.record("C42-derive (must-accept): the committed document, unchanged", "Configuring done", rc, out,
                  want_fail=False, extra={"document_present": (src / DOC_RELATIVE).is_file()})


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--engine-prefix", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--generator", default="Ninja")
    ap.add_argument("--ninja-executable", default="ninja")
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--scratch", default=None)
    args = ap.parse_args(argv)
    matrix.REPO_ROOT = Path(args.repo_root).resolve()
    matrix.ENGINE_PREFIX = Path(args.engine_prefix).resolve()
    matrix.CMAKE = args.cmake_executable
    matrix.GENERATOR = args.generator
    matrix.NINJA = args.ninja_executable
    matrix.PYEXE = args.python_executable
    matrix.SCRATCH = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="te264_c42d_"))
    matrix.SCRATCH.mkdir(parents=True, exist_ok=True)
    try:
        for leg in (leg_missing, leg_unparseable, leg_must_accept):
            matrix._run_leg(leg)
    finally:
        if not args.scratch:
            matrix.rmtree(matrix.SCRATCH)
    print(json.dumps(matrix.RESULTS, indent=2))
    for r in matrix.RESULTS:
        print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['leg']}: expected {r['expected']!r}, "
              f"returncode={r['returncode']}, found_expected_string={r['found_expected_string']}")
    return 0 if matrix.RESULTS and all(r["passed"] for r in matrix.RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
