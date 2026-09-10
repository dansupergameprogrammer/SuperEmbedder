"""tests/te196_manifest_binding_check.py -- TE-196 (U1 slice 4 fix round):
the ctest driver for tests/te196_manifest_binding_test.cpp, the cells for
the TE-193 review's P-3 (and the later items of the same round as their
cells land in that binary).

WHY A DRIVER RATHER THAN A DIRECTLY-REGISTERED C++ TEST. Same reason as
tests/te163_bank_pair_check.py: the binary needs the synthetic mechanism
pair and a scratch directory as runtime arguments, and the pair is minted
by another cell's fixture regenerator in no ctest-guaranteed order, so
this driver builds the (EXCLUDE_FROM_ALL) target on demand, ensures the
pair exists (u1_raw_text_cells_check's own ensure_pair(), the same "one
proven detector" discipline te163_bank_pair_check already applies), and
runs it. MECHANISM only -- no real-artifact leg: every cell in this
driver is a manifest/header/binding construction over a freshly baked
two-document synthetic triple, with no dependence on the real pair.

Exit codes: 0 every evaluated cell PASS; 1 any FAIL.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import u1_raw_text_cells_check as u1raw  # noqa: E402  (sibling module, reused per this file's own header comment)

PAIR_DIR_DEFAULT = REPO_ROOT / "build" / "_scratch" / "u1_pair"
MECH_DIMS = 32
LEG_TIMEOUT_S = 900


class Table:
    def __init__(self) -> None:
        self.failed = False

    def add(self, leg: str, state: str, observed: str) -> None:
        if state in ("FAIL", "RED-UNIMPLEMENTED"):
            self.failed = True
        print(f"[{state}] {leg}: {observed}")
        sys.stdout.flush()


def find_exe(build_dir: Path, name: str) -> Optional[Path]:
    for cand in (build_dir / "tests" / f"{name}.exe", build_dir / "tests" / name,
                 build_dir / f"{name}.exe", build_dir / name):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob(f"{name}.exe")) + [p for p in build_dir.rglob(name) if p.is_file()]
    return hits[0] if hits else None


def run_target(table: Table, cmake: str, build_dir: Path, args: List[str], timeout_s: int) -> None:
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", "te196_manifest_binding_test"],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        table.add("mechanism build", "FAIL",
                  "target build failed:\n" + "\n".join(out.splitlines()[-25:]))
        return
    exe = find_exe(build_dir, "te196_manifest_binding_test")
    if not exe:
        table.add("mechanism build", "FAIL",
                  f"target built but its executable was not found under {build_dir}")
        return
    try:
        run = subprocess.run([str(exe), *args], cwd=REPO_ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        table.add("mechanism process", "FAIL", f"TimeoutExpired after {timeout_s}s")
        return
    for line in run.stdout.splitlines():
        m = re.match(r"\[(PASS|FAIL|MISSING PREREQUISITE|OBSERVED)\]\s*(.*)", line)
        if not m:
            continue
        state, rest = m.group(1), m.group(2)
        if state == "OBSERVED":
            print(f"[OBSERVED] {rest}")
            continue
        if ":" in rest:
            leg, observed = rest.split(":", 1)
        else:
            leg, observed = rest, ""
        table.add(leg.strip(), state, observed.strip())
    if run.returncode not in (0, 1):
        table.add("mechanism process", "FAIL", f"exit code {run.returncode}, stderr tail:\n" +
                  "\n".join((run.stdout + run.stderr).splitlines()[-15:]))
    return


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    table = Table()
    scratch = build_dir / "_scratch" / "te196_manifest_binding"
    scratch.mkdir(parents=True, exist_ok=True)

    u1raw.ensure_pair(PAIR_DIR_DEFAULT)
    mech_args = ["--model", str(PAIR_DIR_DEFAULT / "u1_pair_model.sslm"),
                 "--tokenizer", str(PAIR_DIR_DEFAULT / "u1_pair_tokenizer.sslm"),
                 "--dims", str(MECH_DIMS), "--scratch", str(scratch), "--stem", "mech"]
    run_target(table, args.cmake_executable, build_dir, mech_args, LEG_TIMEOUT_S)

    print(f"\nte196_manifest_binding_check: {'FAILED' if table.failed else 'all evaluated cells PASS'}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))