"""tests/te331_u2_engine_identity_check.py -- TE-331 (U2-3 red suite): the
ctest driver for tests/te331_u2_engine_identity_test.cpp (item 14/M18:
`sslm_build_identity`, `SEMB_ENGINE_LINK_MISMATCH`).

RED TODAY FOR TWO INDEPENDENT REASONS, either of which this driver reports
by name: `SEMB_ENGINE_LINK_MISMATCH` is not a status `semb.h` declares
(the test's own runtime check would print [FAIL] for it, never [MISSING]
or a silent skip -- but the file cannot even run that far), and
`sslm_build_identity` is not a symbol the PINNED ENGINE (SuperSLM 1.5.0 at
D:/_te259/engine-install-v150) defines, so the link itself fails, naming
it -- exactly as the plan's own text predicts ("an engine library defining
neither fails the application's link and names sslm_build_identity").

EXIT CODE CONVENTION (te163's own): 0 only if the target links and every
runtime cell passes; 1 if the link is RED-UNIMPLEMENTED (unresolved
symbol) or a runtime cell fails.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_SYMBOLS = ["sslm_build_identity"]


def build_target(cmake: str, build_dir: Path) -> Tuple[bool, List[str], str]:
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", "te331_u2_engine_identity_test"],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    unresolved = [sym for sym in FROZEN_SYMBOLS
                  if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?"
                               + sym + r"\b", out)]
    return proc.returncode == 0, unresolved, "\n".join(out.splitlines()[-40:])


def find_exe(build_dir: Path, name: str) -> Optional[Path]:
    for cand in (build_dir / "tests" / f"{name}.exe", build_dir / "tests" / name,
                build_dir / f"{name}.exe", build_dir / name):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob(f"{name}.exe")) + [p for p in build_dir.rglob(name) if p.is_file()]
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True, type=Path)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args()

    ok, unresolved, tail = build_target(args.cmake_executable, args.build_dir)
    if not ok:
        if unresolved:
            print(f"[RED-UNIMPLEMENTED] te331_u2_engine_identity_test fails to link, naming: {unresolved} "
                  f"(the pinned engine at this tree's own superslm.lock does not define it)")
        else:
            print(f"[FAIL] build failed for an unexpected reason:\n{tail}")
        return 1

    exe = find_exe(args.build_dir, "te331_u2_engine_identity_test")
    if exe is None:
        print("[FAIL] build reported success but the executable was not found")
        return 1

    argv = [str(exe)]
    if args.model and args.tokenizer:
        argv += ["--model", args.model, "--tokenizer", args.tokenizer]
    proc = subprocess.run(argv, capture_output=True, text=True)
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
