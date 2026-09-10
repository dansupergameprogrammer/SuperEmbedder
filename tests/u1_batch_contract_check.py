"""tests/u1_batch_contract_check.py -- TE-145 (U1 slice 2): the ctest driver
for `semb_encode_batch`'s red suite -- three C++ executables that link
against symbols undefined at this branch's own base c0f52d4
(`semb_encode_batch`, and w_b_corpus_witness_test's own `semb_wb_digest`):

  * tests/u1_batch_contract_test.cpp   -- the precedence/refusal/row-identity
                                          driver, plus C27's corpus form.
                                          Links plain `superembedder`.
  * tests/u1_batch_workspace_test.cpp  -- C4's no-forward-ran seam proof,
                                          C26's two races, C48, C49, C50.
                                          Links `superembedder_testseam`.
  * tests/w_b_corpus_witness_test.cpp  -- the real W-B witness leg.
                                          Links `superembedder_testseam`.

WHY A DRIVER RATHER THAN THREE DIRECTLY-REGISTERED C++ TESTS. Same reason as
tests/u1_raw_text_cells_check.py: each target is EXCLUDE_FROM_ALL, and this
driver builds each on demand, reporting an unresolved `semb_*` symbol as
RED-UNIMPLEMENTED BY NAME rather than breaking the whole tree's configure or
leaving ctest with a "Not Run".

WHAT IT RUNS: MECHANISM (always) -- the synthetic model+tokenizer pair
(tests/fixtures/regenerate_tokenizer_pair_fixture.py: hidden 32, vocab 384,
context_cap 64, <|endoftext|> = 262), reused via u1_raw_text_cells_check's
own ensure_pair() rather than re-derived (this project's own "one proven
detector, not a second invented one" discipline). PRODUCT (when --model and
--tokenizer name the real Qwen3-Embedding-0.6B artifact and its
converter-emitted tokenizer): the same three executables at dims 1024.
Without them the product legs report MISSING PREREQUISITE, named, never FAIL.

Exit codes: 0 every evaluated cell PASS or MISSING PREREQUISITE; 1 any FAIL,
or RED-UNIMPLEMENTED.
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
import u1_raw_text_cells_check as u1raw  # noqa: E402  (sibling module, deliberate reuse per this file's own header comment)

PAIR_DIR_DEFAULT = REPO_ROOT / "build" / "_scratch" / "u1_pair"
FROZEN_SYMBOLS = ["semb_encode_batch", "semb_wb_digest"]
CANDIDATE_DIMS = 1024
MECH_DIMS = 32
MECH_CONTEXT_CAP = 64

# TE-159 item 2 (C-1, D-SLM6348): the driver's own per-subprocess cap, now
# named PER LEG rather than one shared 600 s literal. The mechanism leg's
# fixture is tiny (context_cap 64) and stays well inside 600 s; the product
# workspace leg carries C49's fifty real open/bake/close cycles, and W-B's
# real forward at every open (D-SLM6352: ~19.8 s/open) measured the leg at
# 1,250 s (TE-148 review F-2). The cap below is that measurement plus
# margin -- not a population this round shrinks to fit an unchanged cap.
# TE-183 (D-SLM6435): the 2000 s workspace figure above was itself too small
# -- direct, untimed execution on a shared host measured the real leg
# (65 cells, 0 failures) at approximately 2,760 s. Raised to 3600 s, margin
# over that measurement, per this comment's own instruction (raise the
# figure when the leg's real cost has grown, never shrink a cell's
# population to fit an unchanged cap).
LEG_TIMEOUT_S = {
    "contract": 900,
    "workspace": 3600,
    "wb-witness": 900,
}
DEFAULT_LEG_TIMEOUT_S = 900


def build_target(cmake: str, build_dir: Path, target: str) -> Tuple[bool, List[str], str]:
    """Returns (built, unresolved frozen symbols, output tail)."""
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


def run_target(table: Table, cmake: str, build_dir: Path, target: str, args: List[str], label: str,
               leg_key: str = "") -> None:
    built, unresolved, tail = build_target(cmake, build_dir, target)
    if unresolved:
        table.add(f"{label} link", "RED-UNIMPLEMENTED",
                   f"unresolved symbol(s): {', '.join(unresolved)} -- semb_encode_batch does not exist yet")
        return
    if not built:
        table.add(f"{label} build", "FAIL", "build failed for a reason other than an unresolved frozen symbol:\n" + tail)
        return
    exe = find_exe(build_dir, target)
    if not exe:
        table.add(f"{label} build", "FAIL", f"target {target} built but its executable was not found under {build_dir}")
        return
    timeout_s = LEG_TIMEOUT_S.get(leg_key, DEFAULT_LEG_TIMEOUT_S)
    # TE-159 item 2 (C-1, D-SLM6348): a subprocess timeout is a NAMED FAIL
    # row for this leg, never an uncaught exception. Before this fix,
    # TimeoutExpired propagated out of run_target/run_all/main and killed
    # the whole driver process with a traceback -- dropping every leg after
    # the one that timed out AND the summary line, so ctest reported the
    # entry FAILED with no cell name in the output (TE-148 review C-1).
    try:
        proc = subprocess.run([str(exe), *args], cwd=REPO_ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        table.add(f"{label} process", "FAIL",
                   f"TimeoutExpired after {timeout_s}s (leg={leg_key or 'unknown'}) -- the subprocess was "
                   f"killed; no cell result from this leg is known. Raise LEG_TIMEOUT_S['{leg_key}'] if this "
                   f"leg's own real cost has grown, rather than shrinking any cell's population to fit.")
        return
    for line in proc.stdout.splitlines():
        m = re.match(r"\[(PASS|FAIL|MISSING PREREQUISITE|PHASE|OBSERVED)\]\s*(.*)", line)
        if not m:
            continue
        state, rest = m.group(1), m.group(2)
        if state in ("PHASE", "OBSERVED"):
            continue
        if ":" in rest:
            leg, observed = rest.split(":", 1)
        else:
            leg, observed = rest, ""
        table.add(f"{label} {leg.strip()}", state, observed.strip())
    if proc.returncode not in (0, 1):
        table.add(f"{label} process", "FAIL", f"exit code {proc.returncode}, stderr tail:\n" +
                   "\n".join((proc.stdout + proc.stderr).splitlines()[-15:]))


def run_all(table: Table, cmake: str, build_dir: Path, model: str, tokenizer: str, dims: int,
            context_cap: int, label: str) -> None:
    common = ["--model", model, "--tokenizer", tokenizer, "--dims", str(dims)]
    # TE-182 (D-SLM6375's own remedy, D-SLM6434 item 1): step11's own
    # over-cap document is now sized by TOKENIZED length through the real
    # tokenizer, which refuses in milliseconds -- --skip-step11 (TE-155
    # item 3) is retired; every leg runs step 11 in full.
    contract_args = common + ["--context-cap", str(context_cap)]
    run_target(table, cmake, build_dir, "u1_batch_contract_test", contract_args, f"{label}/contract",
               leg_key="contract")
    run_target(table, cmake, build_dir, "u1_batch_workspace_test", common, f"{label}/workspace",
               leg_key="workspace")
    run_target(table, cmake, build_dir, "w_b_corpus_witness_test", common, f"{label}/wb-witness",
               leg_key="wb-witness")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    table = Table()

    # MECHANISM: always. Reuse the sibling driver's own pair-minting logic
    # rather than re-deriving it.
    pair_dir = PAIR_DIR_DEFAULT
    pair = u1raw.ensure_pair(pair_dir)
    run_all(table, args.cmake_executable, build_dir, str(pair_dir / "u1_pair_model.sslm"),
            str(pair_dir / "u1_pair_tokenizer.sslm"), MECH_DIMS, MECH_CONTEXT_CAP, "mechanism")

    # PRODUCT: only when both real artifacts are named. step11 now runs in
    # full here too (TE-182, D-SLM6375's own remedy) -- the tokenized-length
    # construction refuses in milliseconds against the real candidate's own
    # context_cap (32768), never the 2h3m character-counted forward
    # D-SLM6375 measured.
    if args.model and args.tokenizer:
        run_all(table, args.cmake_executable, build_dir, args.model, args.tokenizer, CANDIDATE_DIMS, 32768,
                "product")
    else:
        table.add("product (all cells)", "MISSING PREREQUISITE",
                   "no --model/--tokenizer given -- the real Qwen3-Embedding-0.6B artifact and its "
                   "converter-emitted tokenizer are not driven here")

    print(f"\nu1_batch_contract_check: {'FAILED' if table.failed else 'all evaluated cells PASS or MISSING PREREQUISITE'}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
