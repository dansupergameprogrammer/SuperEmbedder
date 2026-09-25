"""tests/te331_u2_surface_link_check.py -- TE-331 (U2-7 red suite): the
ctest driver for tests/te331_u2_surface_link_test.cpp.

WHY A DRIVER RATHER THAN A DIRECTLY-REGISTERED C++ TEST. Same reason as
tests/te163_bank_pair_check.py: the target is EXCLUDE_FROM_ALL (it links
against semb_encoder_open_memory / semb_encode_query /
semb_interim_query_token_count, undefined at `fca421b`), so this driver builds it on demand and reports an
unresolved symbol as RED-UNIMPLEMENTED BY NAME.

Without --model/--tokenizer this driver only attempts the build (MECHANISM
leg is not meaningful for this file -- every cell needs the real
tokenizer's real vocabulary, per this file's own header comment) and
reports MISSING PREREQUISITE for the run. With both, it runs the built
executable against the real artifact.

EXIT CODE CONVENTION (te163's own): 0 only if the target links AND (no
artifact given, or the artifact run's own cells all pass); 1 if any symbol
is unresolved (RED-UNIMPLEMENTED) or a run cell fails.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_SYMBOLS = ["semb_encoder_open_memory", "semb_encode_query",
                  "semb_interim_query_token_count"]


def build_target(cmake: str, build_dir: Path, target: str) -> Tuple[bool, List[str], str]:
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", target],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    unresolved = []
    for sym in FROZEN_SYMBOLS:
        if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + sym + r"\b", out):
            unresolved.append(sym)
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

    ok, unresolved, tail = build_target(args.cmake_executable, args.build_dir, "te331_u2_surface_link_test")
    if not ok:
        if unresolved:
            print(f"[RED-UNIMPLEMENTED] te331_u2_surface_link_test fails to link, naming: {unresolved}")
        else:
            print(f"[FAIL] te331_u2_surface_link_test build failed for an unexpected reason:\n{tail}")
        return 1

    exe = find_exe(args.build_dir, "te331_u2_surface_link_test")
    if exe is None:
        print("[FAIL] build reported success but the executable was not found")
        return 1

    if not args.model or not args.tokenizer:
        print("[MISSING PREREQUISITE] the target LINKED (all three verbs now exist) but no "
              "--model/--tokenizer was given, so the real-artifact cells did not run")
        return 0

    scratch = args.build_dir / "_scratch" / "te331_c52_c53"
    scratch.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(exe), "--model", args.model, "--tokenizer", args.tokenizer,
                           "--scratch", str(scratch)], capture_output=True, text=True)
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
