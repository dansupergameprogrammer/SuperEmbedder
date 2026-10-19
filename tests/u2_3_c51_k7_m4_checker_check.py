"""tests/u2_3_c51_k7_m4_checker_check.py -- the checker's constructions among item 13's must-rejects
(`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 item 13, (m4) and (k-7); REL-2 step 1: "C51 (d)'s legs
(k-1)...(k-6) and the checker's (m4)", "(k-7)...(k-9)").

Each construction edits one run of tests/te264_c42_checker_check.py's real-shaped must-accept package (built by
that file's own `write_package`, so the package is the one C42's other constructions refuse from) and runs
tools/check_certified_builds.py over it. Each must refuse on C42 (b') alone, naming the run:

  must-accept   the unedited package is accepted (the control: a checker that refuses everything fails here).
  (m4)          a run file on a foreign engine: the must-accept's msvc19.33-auto@avx2 run with its manifest's
                build_descriptor.engineFlags replaced by the clang-cl engine's digest, run.json re-bound to the
                edited manifest -> REFUSED C42(b') msvc19.33-auto@avx2.
  (k-7)         a record that pins a place, the adversary's construction (TE-297 sec 3, configure A): the run's
                compile-flags.json replaced by the record the TE-292 rule writes for configure A, which keeps
                -external:ID:\\_te259\\engine-install-v150\\include on every library TU, with the cell's, the
                manifest's and run.json's compileFlags set to that record's digest so every other binding holds
                -> REFUSED C42(b') msvc19.33-auto@avx2 location -external:ID:\\_te259\\engine-install-v150\\include.
  (k-7) engine  the same for engine-flags.json, one engine TU's -I<src>/include restored to an absolute clone path
                -> REFUSED C42(b') msvc19.33-auto@avx2 location <that argument>.

Pure Python over files: runs on every host.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import te264_c42_checker_check as pkg  # noqa: E402

CELL = "msvc19.33-auto@avx2"
PLACE = r"-external:ID:\_te259\engine-install-v150\include"   # TE-297 sec 3, configure A
CLONE_INCLUDE = r"-ID:\_te297\superslm-src\include"           # an engine TU's -I<src>/include, unrelativized


def run_checker(root: Path) -> tuple[int, set[str], list[str]]:
    proc = subprocess.run([sys.executable, str(pkg.CHECKER), "--root", str(root)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    out = proc.stdout + proc.stderr
    lines = [l for l in out.splitlines() if l.startswith("REFUSED C42")]
    return proc.returncode, set(re.findall(r"^REFUSED C42\(([a-i]'?)\)", out, re.M)), lines


def rebind(root: Path, doc: dict, cell: str, key: str, value: str, list_too: bool) -> None:
    """Sets the run's manifest build_descriptor[key] (and the list cell's, when list_too) to `value`, and re-binds
    run.json to the edited manifest (its buildDescriptor copy and manifestSha256)."""
    d = root / pkg.EVIDENCE / cell
    manifest = json.loads((d / "bake-manifest.semb.json").read_bytes())
    manifest["build_descriptor"][key] = value
    data = pkg.dump(manifest)
    (d / "bake-manifest.semb.json").write_bytes(data)
    run = json.loads((d / "run.json").read_bytes())
    run["buildDescriptor"] = manifest["build_descriptor"]
    run["manifestSha256"] = pkg.sha(data)
    (d / "run.json").write_bytes(pkg.dump(run))
    if list_too:
        edited = copy.deepcopy(doc)
        for b in edited["builds"]:
            if b["id"] == cell:
                b[key] = value
        pkg.write_doc(root, edited)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch", type=Path, default=None)
    args = ap.parse_args(argv)
    scratch = args.scratch or Path(tempfile.mkdtemp(prefix="c51_k7_m4_"))
    failed = False

    def report(ok: bool, cell: str, detail: str) -> None:
        nonlocal failed
        print(f"[{'PASS' if ok else 'FAIL'}] {cell} -- {detail}", flush=True)
        failed |= not ok

    def fresh(name: str) -> tuple[Path, dict]:
        root = scratch / name
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        return root, pkg.write_package(root)

    def refused_naming(root: Path, cell: str, want_line: str) -> None:
        rc, clauses, lines = run_checker(root)
        hit = [l for l in lines if l.startswith(want_line)]
        report(rc == 1 and clauses == {"b'"} and bool(hit), cell,
               f"exit={rc}; refused clauses={sorted(clauses)} (want ['b'']); want a line starting {want_line!r}; "
               f"got {lines[:4]}")

    try:
        root, _ = fresh("accept")
        rc, clauses, lines = run_checker(root)
        report(rc == 0 and not clauses, "must-accept: the real-shaped two-cell package is accepted",
               f"exit={rc}; refused {lines[:3]}")

        # (m4): the run's manifest names the clang-cl engine's record digest.
        root, p = fresh("m4_foreign_engine")
        foreign = pkg.flag_digest(pkg.engine_record("clangcl"))
        rebind(root, p["list"], CELL, "engineFlags", foreign, list_too=False)
        refused_naming(root, f"(m4) the {CELL} run with build_descriptor.engineFlags replaced by the clang-cl "
                             f"engine's digest is refused on C42 (b') naming the run", f"REFUSED C42(b') {CELL}")

        # (k-7): the product record keeps configure A's place on every library TU.
        root, p = fresh("k7_compile_flags_place")
        rec = pkg.product_record("msvc")
        for unit in rec.values():
            unit["includes"] = [PLACE if a.startswith("-external:I<engine>") else a for a in unit["includes"]]
        d = root / pkg.EVIDENCE / CELL
        (d / "compile-flags.json").write_bytes(pkg.dump({"family": "msvc", "record": rec}))
        rebind(root, p["list"], CELL, "compileFlags", pkg.flag_digest(rec), list_too=True)
        refused_naming(root, f"(k-7) the {CELL} run's compile-flags.json keeps {PLACE} on {len(rec)} of {len(rec)} "
                             f"library TUs, every digest bound to it: refused on C42 (b') naming the location",
                       f"REFUSED C42(b') {CELL} location {PLACE}")

        # (k-7) engine half: one engine TU's -I<src>/include restored to its absolute clone path.
        root, p = fresh("k7_engine_flags_place")
        rec = pkg.engine_record("msvc")
        first = sorted(rec)[0]
        rec[first]["includes"] = [CLONE_INCLUDE if a == "-I<src>/include" else a for a in rec[first]["includes"]]
        d = root / pkg.EVIDENCE / CELL
        (d / "engine-flags.json").write_bytes(pkg.dump({"family": "msvc", "record": rec}))
        rebind(root, p["list"], CELL, "engineFlags", pkg.flag_digest(rec), list_too=True)
        refused_naming(root, f"(k-7) the {CELL} run's engine-flags.json with {first}'s -I<src>/include restored to "
                             f"{CLONE_INCLUDE}, every digest bound to it: refused on C42 (b') naming the location",
                       f"REFUSED C42(b') {CELL} location {CLONE_INCLUDE}")
    finally:
        if not args.scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    print(f"u2_3_c51_k7_m4_checker_check: {'FAILED' if failed else 'every construction PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
