"""tests/te194_query_workspace_check.py -- TE-194 (U1 slice 5): the ctest
driver for tests/te194_query_workspace_test.cpp (cell 3 / C26's remaining
two races, Claude/Bach/briefs/te194-slice5-red.md).

Same red-first shape as tests/te194_query_check.py: EXCLUDE_FROM_ALL target
(links against semb_query_open/semb_query_encode/semb_query_close,
undefined at this branch's own base 21b1735), built on demand, unresolved
symbols reported by name as RED-UNIMPLEMENTED. The mechanism tokenizer-pair
fixture is sufficient here (the race construction does not depend on which
artifact is open), so this driver runs one leg, not a mechanism/product
split.

Exit codes: 0 PASS/MISSING PREREQUISITE/RED-UNIMPLEMENTED; 1 FAIL.
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

FROZEN_SYMBOLS = ["semb_query_open", "semb_query_encode", "semb_query_close"]
LEG_TIMEOUT_S = 900


def build_target(cmake: str, build_dir: Path, config: str = "") -> Tuple[bool, List[str], str]:
    cmd = [cmake, "--build", str(build_dir), "--target", "te194_query_workspace_test"]
    if config:
        cmd += ["--config", config]
    proc = subprocess.run(cmd,
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    unresolved = [s for s in FROZEN_SYMBOLS
                  if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + s + r"\b", out)]
    return proc.returncode == 0, unresolved, "\n".join(out.splitlines()[-25:])


def find_exe(build_dir: Path, exe: str = "") -> "Path | None":
    # --exe is $<TARGET_FILE:te194_query_workspace_test>, passed by CMake: the
    # target is defined in the top-level directory (deferred), so it lands
    # wherever the generator puts that directory's outputs, not in tests/.
    if exe:
        return Path(exe) if Path(exe).exists() else None
    for cand in (build_dir / "tests" / "te194_query_workspace_test.exe", build_dir / "tests" / "te194_query_workspace_test"):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob("te194_query_workspace_test.exe"))
    return hits[0] if hits else None


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--exe", default="", help="the built test executable ($<TARGET_FILE:te194_query_workspace_test>)")
    ap.add_argument("--config", default="", help="the configuration ctest runs ($<CONFIG>) for multi-config generators")
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)

    pair_dir = REPO_ROOT / "build" / "_scratch" / "u1_pair"
    u1raw.ensure_pair(pair_dir)
    model = pair_dir / "u1_pair_model.sslm"
    tokenizer = pair_dir / "u1_pair_tokenizer.sslm"
    scratch = build_dir / "_scratch" / "te194_query_workspace"
    scratch.mkdir(parents=True, exist_ok=True)

    built, unresolved, tail = build_target(args.cmake_executable, build_dir, args.config)
    if unresolved:
        print(f"[RED-UNIMPLEMENTED] te194_query_workspace_test link: unresolved symbol(s): "
              f"{', '.join(unresolved)} -- the query verbs do not exist yet")
        # RED-UNIMPLEMENTED is a non-zero exit, matching this suite's own
        # established convention (tests/te163_bank_pair_check.py's Table
        # class: "if state in (FAIL, RED-UNIMPLEMENTED): self.failed = True").
        # A red-first cell reads as a failing ctest until the suite is green
        # -- that is the whole point of registering it before the build
        # exists, and a driver that exits 0 here would make this round's own
        # "existing suite still green" exit condition silently swallow the
        # cells this round exists to add.
        return 1
    if not built:
        print("[FAIL] te194_query_workspace_test build: build failed for a reason other than an "
              f"unresolved query symbol:\n{tail}")
        return 1
    exe = find_exe(build_dir, args.exe)
    if not exe:
        print(f"[FAIL] te194_query_workspace_test build: target built but its executable was not found under {build_dir}" +
              (f" (expected {args.exe})" if args.exe else ""))
        return 1

    try:
        proc = subprocess.run([str(exe), "--model", str(model), "--tokenizer", str(tokenizer), "--scratch", str(scratch)],
                              cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=LEG_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] te194_query_workspace_test process: TimeoutExpired after {LEG_TIMEOUT_S}s")
        return 1

    print(proc.stdout)
    failed = "[FAIL]" in proc.stdout or proc.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
