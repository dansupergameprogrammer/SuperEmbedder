"""tests/te237_bank_cross_handle_check.py -- TE-237 (U1 slice 6 fix-round
pins): the ctest driver for tests/te237_bank_cross_handle_test.cpp (the S-3
cross-handle construction, Claude/Bach/briefs/te237-slice6-s3-pins.md).

Same red-first shape as tests/te194_query_workspace_check.py:
EXCLUDE_FROM_ALL target (links against the semb_bank_test_seam_* snapshot
park surface, undefined at this branch's own base fe0c0e0 -- no test-seam
hook exists inside semb_bank_open), built on demand, unresolved symbols
reported by name as RED-UNIMPLEMENTED. The exact hook contract the builder
must satisfy is in tests/te237_bank_cross_handle_test.cpp's header comment
and tests/support/semb_bank_open_seam.h.

The mechanism tokenizer-pair fixture is sufficient (the cross-handle
construction does not depend on which artifact is open), so this driver
runs one leg, not a mechanism/product split.

Exit codes: 0 PASS/MISSING PREREQUISITE; 1 FAIL or RED-UNIMPLEMENTED (a
red-first cell reads as a failing ctest until the suite is green).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import u1_raw_text_cells_check as u1raw  # noqa: E402

SEAM_SYMBOLS = [
    "semb_bank_test_seam_arm_snapshot_park",
    "semb_bank_test_seam_snapshot_parked",
    "semb_bank_test_seam_snapshot_wait_parked",
    "semb_bank_test_seam_snapshot_release",
    "semb_bank_test_seam_snapshot_reset",
]
LEG_TIMEOUT_S = 900


def build_target(cmake: str, build_dir: Path) -> Tuple[bool, List[str], str]:
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", "te237_bank_cross_handle_test"],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    unresolved = [s for s in SEAM_SYMBOLS
                  if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + s + r"\b", out)]
    return proc.returncode == 0, unresolved, "\n".join(out.splitlines()[-25:])


def find_exe(build_dir: Path) -> "Path | None":
    for cand in (build_dir / "tests" / "te237_bank_cross_handle_test.exe", build_dir / "tests" / "te237_bank_cross_handle_test"):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob("te237_bank_cross_handle_test.exe"))
    return hits[0] if hits else None


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)

    pair_dir = REPO_ROOT / "build" / "_scratch" / "u1_pair"
    u1raw.ensure_pair(pair_dir)
    model = pair_dir / "u1_pair_model.sslm"
    tokenizer = pair_dir / "u1_pair_tokenizer.sslm"
    scratch = build_dir / "_scratch" / "te237_bank_cross_handle"
    scratch.mkdir(parents=True, exist_ok=True)

    built, unresolved, tail = build_target(args.cmake_executable, build_dir)
    if unresolved:
        print(f"[RED-UNIMPLEMENTED] te237_bank_cross_handle_test link: unresolved symbol(s): "
              f"{', '.join(unresolved)} -- the snapshot-materialization park hook does not exist inside "
              f"semb_bank_open yet; its exact contract is in tests/te237_bank_cross_handle_test.cpp's header "
              f"comment (the S-3 remedy must build the complete handle before taking RegistryMutex, and the "
              f"hook parks the materialization block wherever it lives)")
        # RED-UNIMPLEMENTED is a non-zero exit, the established convention of
        # this suite (tests/te194_query_workspace_check.py's own rationale): a
        # red-first cell reads as a failing ctest until the suite is green.
        return 1
    if not built:
        print("[FAIL] te237_bank_cross_handle_test build: build failed for a reason other than an "
              f"unresolved seam symbol:\n{tail}")
        return 1
    exe = find_exe(build_dir)
    if not exe:
        print(f"[FAIL] te237_bank_cross_handle_test build: target built but its executable was not found under {build_dir}")
        return 1

    try:
        proc = subprocess.run([str(exe), "--model", str(model), "--tokenizer", str(tokenizer), "--scratch", str(scratch)],
                              cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=LEG_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] te237_bank_cross_handle_test process: TimeoutExpired after {LEG_TIMEOUT_S}s")
        return 1

    print(proc.stdout)
    failed = "[FAIL]" in proc.stdout or proc.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))