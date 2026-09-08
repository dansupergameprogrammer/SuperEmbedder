"""tests/te163_bank_pair_check.py -- TE-163 (U1 slice 4): the ctest driver
for tests/te163_bank_pair_test.cpp (cells 1, 2, 3, 5, 6 of this round's own
dispatch, Claude/Bach/briefs/te163-slice4-red.md).

WHY A DRIVER RATHER THAN A DIRECTLY-REGISTERED C++ TEST. Same reason as
tests/u1_batch_contract_check.py: the target is EXCLUDE_FROM_ALL (it links
against semb_bake_to_path / semb_bank_open / semb_bank_close, undefined at
this branch's own base 7af22da), so this driver builds it on demand and
reports an unresolved symbol as RED-UNIMPLEMENTED BY NAME.

WHAT IT RUNS: MECHANISM (always) -- the synthetic model+tokenizer pair
(tests/fixtures/regenerate_tokenizer_pair_fixture.py, reused via
u1_raw_text_cells_check's own ensure_pair(), the same "one proven detector"
discipline u1_batch_contract_check.py already applies), against the
committed sixteen-document W-B fixture (tests/fixtures/wb/wb-corpus.jsonl).
PRODUCT (when --model and --tokenizer name the real candidate artifact and
its converter-emitted tokenizer): the same binary with --real and
--corpus-239, driving the 239-document real-artifact bake this round's own
dispatch requires, timed.

THE SUPERFAISS MUST-ACCEPT (this round's own dispatch: "The must-accept is
SuperFAISS's own reader... run it from your test, never copy it into the
tree"): after the mechanism leg bakes the WB fixture, this driver imports
D:\\SuperFAISS\\tools\\wvbank.py IN PLACE (sys.path insertion, no copy) and
calls its own read_bank() against the freshly-baked .wvbank.json, comparing
the returned header and rows against the values this driver independently
knows the bake must have produced (count, dims, ids, and the row bytes read
directly off the SAME .wvbank.bin file the C++ binary just wrote and the
suite's own cells already graded bit-identical to a fresh
semb_encode_batch call).

Exit codes: 0 every evaluated cell PASS or MISSING PREREQUISITE; 1 any FAIL
or RED-UNIMPLEMENTED.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import u1_raw_text_cells_check as u1raw  # noqa: E402  (sibling module, reused per this file's own header comment)

SUPERFAISS_TOOLS = Path(r"D:\SuperFAISS\tools")
PAIR_DIR_DEFAULT = REPO_ROOT / "build" / "_scratch" / "u1_pair"
FROZEN_SYMBOLS = ["semb_bake_to_path", "semb_bank_open", "semb_bank_close"]
CANDIDATE_DIMS = 1024
MECH_DIMS = 32
LEG_TIMEOUT_S_MECHANISM = 900
# The real-artifact leg carries a 239-document bake (~19.8s open +
# encode time; TE-145's own W-B leg measured a comparable real-artifact
# workspace leg at 1,250s, D-SLM6352/TE-148 review F-2) plus this round's
# own cells 2/3/5/6 rerun against the real pair -- generous margin over that
# precedent, named per leg rather than one shared literal (TE-159 item 2).
LEG_TIMEOUT_S_PRODUCT = 2400


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
    built, unresolved, tail = build_target(cmake, build_dir, "te163_bank_pair_test")
    if unresolved:
        table.add(f"{label} link", "RED-UNIMPLEMENTED",
                   f"unresolved symbol(s): {', '.join(unresolved)} -- the bake/bank primitives do not exist yet")
        return
    if not built:
        table.add(f"{label} build", "FAIL", "build failed for a reason other than an unresolved frozen symbol:\n" + tail)
        return
    exe = find_exe(build_dir, "te163_bank_pair_test")
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
        if ":" in rest:
            leg, observed = rest.split(":", 1)
        else:
            leg, observed = rest, ""
        table.add(leg.strip(), state, observed.strip())
    if proc.returncode not in (0, 1):
        table.add(f"{label} process", "FAIL", f"exit code {proc.returncode}, stderr tail:\n" +
                   "\n".join((proc.stdout + proc.stderr).splitlines()[-15:]))
    return proc


def superfaiss_must_accept(table: Table, label: str, stem: Path) -> None:
    json_path = stem.with_suffix("").with_suffix("") if False else Path(str(stem) + ".wvbank.json")
    bin_path = Path(str(stem) + ".wvbank.bin")
    if not json_path.exists() or not bin_path.exists():
        table.add(f"{label} SuperFAISS must-accept", "MISSING PREREQUISITE",
                   f"{json_path} / {bin_path} not present -- the bake leg above did not produce them")
        return
    try:
        sys.path.insert(0, str(SUPERFAISS_TOOLS))
        import wvbank  # noqa: E402  -- SuperFAISS's own module, run in place, never copied (this round's own contract)
        header, rows = wvbank.read_bank(str(json_path))
    except Exception as exc:  # noqa: BLE001 -- a raised exception here IS the finding
        table.add(f"{label} SuperFAISS must-accept (D:/SuperFAISS/tools/wvbank.py read_bank)", "FAIL",
                   f"SuperFAISS's own reader raised on a SuperEmbedder-emitted bank: {exc!r}")
        return
    dims = int(header["dims"])
    count = int(header["count"])
    payload = bin_path.read_bytes()
    expected_rows = [list(struct.unpack_from(f"<{dims}f", payload, r * dims * 4)) for r in range(count)]
    rows_equal = rows == expected_rows
    table.add(f"{label} SuperFAISS must-accept (D:/SuperFAISS/tools/wvbank.py read_bank)",
              "PASS" if rows_equal else "FAIL",
              f"schemaVersion={header.get('schemaVersion')} count={count} dims={dims} "
              f"rows_equal_to_bin_payload={rows_equal}")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    table = Table()
    scratch = build_dir / "_scratch" / "te163_bank_pair"
    scratch.mkdir(parents=True, exist_ok=True)
    wb_corpus = REPO_ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"
    corpus_239 = REPO_ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"

    # MECHANISM: always.
    pair_dir = PAIR_DIR_DEFAULT
    u1raw.ensure_pair(pair_dir)
    mech_args = ["--model", str(pair_dir / "u1_pair_model.sslm"), "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm"),
                 "--dims", str(MECH_DIMS), "--scratch", str(scratch), "--wb-corpus", str(wb_corpus), "--stem", "mech"]
    run_target(table, args.cmake_executable, build_dir, mech_args, "mechanism", LEG_TIMEOUT_S_MECHANISM)
    superfaiss_must_accept(table, "mechanism", scratch / "mech_wb")

    # PRODUCT: only when both real artifacts are named.
    if args.model and args.tokenizer:
        prod_args = ["--model", args.model, "--tokenizer", args.tokenizer, "--dims", str(CANDIDATE_DIMS),
                     "--scratch", str(scratch), "--wb-corpus", str(wb_corpus), "--corpus-239", str(corpus_239),
                     "--real", "--stem", "prod"]
        run_target(table, args.cmake_executable, build_dir, prod_args, "product", LEG_TIMEOUT_S_PRODUCT)
        superfaiss_must_accept(table, "product", scratch / "prod_wb")
    else:
        table.add("product (all cells)", "MISSING PREREQUISITE",
                   "no --model/--tokenizer given -- the real candidate artifact and its converter-emitted "
                   "tokenizer are not driven here")

    print(f"\nte163_bank_pair_check: {'FAILED' if table.failed else 'all evaluated cells PASS or MISSING PREREQUISITE'}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
