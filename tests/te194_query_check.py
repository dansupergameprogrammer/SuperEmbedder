"""tests/te194_query_check.py -- TE-194 (U1 slice 5): the ctest driver for
tests/te194_query_test.cpp (cells 1, 2, 6 of this round's own dispatch,
Claude/Bach/briefs/te194-slice5-red.md).

WHY A DRIVER RATHER THAN A DIRECTLY-REGISTERED C++ TEST -- the same reason
as tests/te163_bank_pair_check.py: the target is EXCLUDE_FROM_ALL (it links
against semb_query_open/semb_query_encode/semb_query_close/semb_fingerprint_of,
undefined at this branch's own base 21b1735), so this driver builds it on
demand and reports an unresolved symbol as RED-UNIMPLEMENTED BY NAME.

WHAT IT RUNS: MECHANISM (always) -- artifact B is the synthetic tokenizer-pair
fixture (tests/fixtures/regenerate_tokenizer_pair_fixture.py), baked against
tests/fixtures/wb/wb-corpus.jsonl (the committed sixteen-document W-B
corpus, reused here as a small, already-committed bake source -- this cell
needs A bank to open, not W-B's own witness properties). PRODUCT (when
--model-a/--tokenizer-a name the real candidate artifact and its
converter-emitted tokenizer, with --real): artifact A is the real
candidate, exercising cell 2's own C8 legs (which need two artifact-distinct
encoders).

Exit codes: 0 every evaluated cell PASS, MISSING PREREQUISITE, or
RED-UNIMPLEMENTED; 1 any FAIL or an unresolved-symbol build that turns out
to fail for a DIFFERENT reason than the four query verbs.
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
import u1_raw_text_cells_check as u1raw  # noqa: E402  (sibling module, reused for ensure_pair(), per this tree's own convention)

FROZEN_SYMBOLS = ["semb_query_open", "semb_query_encode", "semb_query_close", "semb_fingerprint_of"]
LEG_TIMEOUT_S_MECHANISM = 900
LEG_TIMEOUT_S_PRODUCT = 1800


def build_target(cmake: str, build_dir: Path, target: str) -> Tuple[bool, List[str], str]:
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", target],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    out = proc.stdout + proc.stderr
    unresolved = []
    for sym in FROZEN_SYMBOLS:
        if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + sym + r"\b", out):
            unresolved.append(sym)
    return proc.returncode == 0, unresolved, "\n".join(out.splitlines()[-25:])


def find_exe(build_dir: Path, name: str) -> Optional[Path]:
    for cand in (build_dir / "tests" / f"{name}.exe", build_dir / "tests" / name,
                 build_dir / f"{name}.exe", build_dir / name):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob(f"{name}.exe")) + [p for p in build_dir.rglob(name) if p.is_file()]
    return hits[0] if hits else None


class Table:
    def __init__(self) -> None:
        self.failed = False

    def add(self, leg: str, state: str, observed: str) -> None:
        if state in ("FAIL", "RED-UNIMPLEMENTED"):
            self.failed = True
        print(f"[{state}] {leg}: {observed}")
        sys.stdout.flush()


def run_target(table: Table, cmake: str, build_dir: Path, args: List[str], label: str, timeout_s: int) -> None:
    built, unresolved, tail = build_target(cmake, build_dir, "te194_query_test")
    if unresolved:
        table.add(f"{label} link", "RED-UNIMPLEMENTED",
                   f"unresolved symbol(s): {', '.join(unresolved)} -- the query verbs do not exist yet")
        return
    if not built:
        table.add(f"{label} build", "FAIL", "build failed for a reason other than an unresolved query symbol:\n" + tail)
        return
    exe = find_exe(build_dir, "te194_query_test")
    if not exe:
        table.add(f"{label} build", "FAIL", f"target built but its executable was not found under {build_dir}")
        return
    try:
        proc = subprocess.run([str(exe), *args], cwd=REPO_ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        table.add(f"{label} process", "FAIL", f"TimeoutExpired after {timeout_s}s")
        return
    for line in proc.stdout.splitlines():
        m = re.match(r"\[(PASS|FAIL|MISSING PREREQUISITE|OBSERVED)\]\s*(.*)", line)
        if not m:
            continue
        state, rest = m.group(1), m.group(2)
        if state == "OBSERVED":
            print(f"[OBSERVED] {rest}")
            continue
        table.add(f"{label} {rest.split(':', 1)[0]}", state, rest.split(':', 1)[1].strip() if ':' in rest else "")
    if proc.returncode != 0 and not any(l.startswith("[FAIL]") or l.startswith("[RED-UNIMPLEMENTED]") for l in proc.stdout.splitlines()):
        table.add(f"{label} process", "FAIL", f"exit code {proc.returncode} with no parsed cell explaining it:\n{proc.stdout[-2000:]}")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", default="", help="the real candidate model (artifact A)")
    ap.add_argument("--tokenizer", default="", help="the real candidate tokenizer (artifact A)")
    args = ap.parse_args(argv)

    build_dir = Path(args.build_dir)
    table = Table()

    pair_dir = REPO_ROOT / "build" / "_scratch" / "u1_pair"
    u1raw.ensure_pair(pair_dir)
    model_b = pair_dir / "u1_pair_model.sslm"
    tokenizer_b = pair_dir / "u1_pair_tokenizer.sslm"

    scratch = build_dir / "_scratch" / "te194_query"
    scratch.mkdir(parents=True, exist_ok=True)
    wb_corpus = REPO_ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"

    mech_args = ["--model-b", str(model_b), "--tokenizer-b", str(tokenizer_b),
                 "--wb-corpus", str(wb_corpus), "--scratch", str(scratch)]
    run_target(table, args.cmake_executable, build_dir, mech_args, "mechanism", LEG_TIMEOUT_S_MECHANISM)

    if args.model and args.tokenizer:
        prod_args = mech_args + ["--real", "--model-a", args.model, "--tokenizer-a", args.tokenizer]
        run_target(table, args.cmake_executable, build_dir, prod_args, "product", LEG_TIMEOUT_S_PRODUCT)
    else:
        table.add("product (C8's three legs)", "MISSING PREREQUISITE",
                  "requires --model --tokenizer naming the real candidate artifact")

    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
