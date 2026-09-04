"""tests/u1_trailing_special_mutants_check.py -- TE-92: an INDEPENDENT
construction proving that the tokenization-parity oracle the frozen raw-text
cells compare against (the existing interim token-id/PS-N path, C12b's
instrument `semb_c12b_row_digest`) DETECTS an omitted, doubled or wrong
trailing-special-token composition -- so equality with that oracle
(tests/u1_raw_text_parity_test.cpp, P-01) pins the frozen path's composition
and not only its BPE.

This runs entirely through the product's EXISTING interim surface, so it is
executable on unmodified main today; it is the commissioning of the oracle
(StandardsDocument.md sec 5.4: a must-reject producible by the instrument's
real data path, authored by a seat other than the frozen path's builder),
not a cell against the unbuilt frozen verbs -- it is expected GREEN, and a
red here means the parity oracle cannot see the composition class at all.

ARMS, each an instrument run over the same corpus rows, compared on the
per-row `psn_vector_sha256` column (what a user receives):

  A0 correct     `--append-token-id <id>` over content ids         (twice: must-accept, byte-identical)
  A1 doubled     content ids + [<id>] handed in, `--append-token-id <id>`  -> [.., id, id]
  A2 wrong id    `--append-token-id <wrong>` over content ids       -> [.., wrong]   (the candidate's
                 wrong id is 151645 = <|im_end|>, the flag D-SLM4731 mistook for the append)
  A3 omitted     one run per row: content[:-1] handed in with `--append-token-id content[-1]`
                 -> exactly the content, no end token (rows with >= 2 content ids)

Every mutant arm must differ from A0 on EVERY row it covers. Synthetic pair:
all 23 non-empty mechanism records. Real candidate (--model): the committed
239-row C12b corpus, A1/A2 over --limit rows (default all), A3 over
--omitted-rows rows (default 8: each is a full model open).

Exit codes: 0 every arm fired on every row; 1 a dead arm, a refusal, or the
instrument absent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REAL_CORPUS = FIXTURES / "c12b" / "corpus-239.tokens.tsv"
PAIR_DIR_DEFAULT = REPO_ROOT / "build" / "_scratch" / "u1_pair"
CANDIDATE_APPEND_ID = 151643
CANDIDATE_WRONG_ID = 151645

Row = Tuple[int, str, str, str]


def parse_rows(path: Path) -> Dict[str, Row]:
    rows: Dict[str, Row] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        label, n, seam, sel, vec = parts[:5]
        rows[label] = (int(n), seam, sel, vec)
    return rows


def read_corpus(path: Path) -> List[Tuple[str, List[int]]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        label, csv = line.split("\t")[:2]
        ids = [int(x) for x in csv.split(",") if x]
        if ids:
            out.append((label, ids))
    return out


def write_corpus(rows: List[Tuple[str, List[int]]], path: Path) -> Path:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for label, ids in rows:
            f.write(label + "\t" + ",".join(str(x) for x in ids) + "\n")
    return path


class Instrument:
    def __init__(self, exe: Path, scratch: Path):
        self.exe, self.scratch, self.calls = exe, scratch, 0
        scratch.mkdir(parents=True, exist_ok=True)

    def run(self, model: Path, corpus: Path, append_id: int, tag: str) -> Dict[str, Row]:
        self.calls += 1
        out = self.scratch / f"mut_{self.calls:03d}_{tag}.tsv"
        cmd = [str(self.exe), "--model", str(model), "--corpus", str(corpus), "--out", str(out),
               "--leg", "chunk", "--chunk-budget", "0", "--select", "last", "--append-token-id", str(append_id)]
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"instrument exited {proc.returncode}: {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
        return parse_rows(out)


def ensure_pair(pair_dir: Path) -> dict:
    manifest = pair_dir / "u1_pair.manifest.json"
    if not manifest.exists():
        cmd = [sys.executable, str(FIXTURES / "regenerate_tokenizer_pair_fixture.py"), "--lock", "superslm.lock",
               "--out-dir", str(pair_dir)]
        src = os.environ.get("SEMB_TEST_ENGINE_SOURCE")
        if src:
            cmd += ["--source", src]
        subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return json.loads(manifest.read_text(encoding="utf-8"))


def mechanism_corpus(pair_dir: Path) -> List[Tuple[str, List[int]]]:
    out = []
    for line in (pair_dir / "u1_mechanism_expected_ids.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        label, csv, _hex = line.split("\t")[:3]
        ids = [int(x) for x in csv.split(",") if x]
        if ids:
            out.append((label, ids))
    return out


def run_arms(inst: Instrument, model: Path, corpus: List[Tuple[str, List[int]]], append_id: int, wrong_id: int,
             omitted_rows: int, tag: str, verdict) -> None:
    scratch = inst.scratch
    t0 = time.perf_counter()
    base_path = write_corpus(corpus, scratch / f"{tag}_base.tsv")
    a0 = inst.run(model, base_path, append_id, f"{tag}_a0")
    a0b = inst.run(model, base_path, append_id, f"{tag}_a0b")
    same = all(a0[l][3] == a0b[l][3] for l in a0)
    verdict(same and len(a0) == len(corpus), f"{tag} A0 must-accept: two correct runs byte-identical on every row",
            f"{len(a0)} rows in {time.perf_counter() - t0:.1f}s")

    doubled = [(l, ids + [append_id]) for l, ids in corpus]
    a1 = inst.run(model, write_corpus(doubled, scratch / f"{tag}_doubled.tsv"), append_id, f"{tag}_a1")
    # A row whose content is nothing but the appended id becomes, doubled, a
    # UNIFORM sequence one token longer -- and a uniform sequence's last
    # position can be length-invariant by construction (every position's
    # value vector is identical, so attention over them returns that value
    # whatever the weights). Executed on the synthetic pair: content [262],
    # [262,262], [262,262,262] and seven 262s all emit one vector, as do
    # uniform 97 and 300; on the real candidate the three end-token lengths
    # emit three DIFFERENT vectors. Uniform rows are therefore reported, never
    # counted: the arm's claim is over documents that carry content.
    uniform = {l for l, ids in corpus if set(ids) == {append_id}}
    dead = [l for l in a0 if l not in uniform and a1[l][3] == a0[l][3]]
    uniform_moved = [l for l in uniform if a1[l][3] != a0[l][3]]
    counted = len(a0) - len(uniform)
    verdict(not dead and len(a1) == len(a0) and counted > 0,
            f"{tag} A1 DOUBLED end token moves the vector on every row that carries content",
            f"{counted - len(dead)} of {counted} moved; dead: {dead or 'none'}; uniform end-token-only rows "
            f"(reported, not counted): {sorted(uniform) or 'none'}, of which moved: {sorted(uniform_moved) or 'none'}")

    a2 = inst.run(model, base_path, wrong_id, f"{tag}_a2")
    dead = [l for l in a0 if a2[l][3] == a0[l][3]]
    verdict(not dead and len(a2) == len(a0), f"{tag} A2 WRONG end token id ({wrong_id} for {append_id}) moves the vector on every row",
            f"{len(a0) - len(dead)} of {len(a0)} moved; dead: {dead or 'none'}")

    t1 = time.perf_counter()
    candidates = [(l, ids) for l, ids in corpus if len(ids) >= 2][:omitted_rows]
    dead, done = [], 0
    for l, ids in candidates:
        one = write_corpus([(l, ids[:-1])], scratch / f"{tag}_omit_{done:03d}.tsv")
        a3 = inst.run(model, one, ids[-1], f"{tag}_a3_{done:03d}")
        if a3[l][3] == a0[l][3]:
            dead.append(l)
        done += 1
    verdict(done > 0 and not dead, f"{tag} A3 OMITTED end token (content alone) moves the vector on every row covered",
            f"{done - len(dead)} of {done} moved in {time.perf_counter() - t1:.1f}s; dead: {dead or 'none'}")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instrument", default="")
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--model", default=os.environ.get("SEMB_C12B_MODEL", ""))
    ap.add_argument("--pair-dir", default=str(PAIR_DIR_DEFAULT))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--omitted-rows", type=int, default=8)
    args = ap.parse_args(argv)
    failed = False
    rows: List[Tuple[str, str, str]] = []

    def verdict(ok, cell, observed, missing=False):
        nonlocal failed
        state = "MISSING PREREQUISITE" if missing else ("PASS" if ok else "FAIL")
        if not ok and not missing:
            failed = True
        rows.append((cell, state, observed))
        print(f"[{state}] {cell}: {observed}")
        sys.stdout.flush()

    if not args.instrument or not Path(args.instrument).exists():
        print("u1_trailing_special_mutants_check: FAIL -- the C12b instrument (semb_c12b_row_digest) is not built")
        return 1
    inst = Instrument(Path(args.instrument), Path(args.build_dir) / "_u1_mutants")

    pair_dir = Path(args.pair_dir)
    try:
        pair = ensure_pair(pair_dir)
        corpus = mechanism_corpus(pair_dir)
        run_arms(inst, pair_dir / "u1_pair_model.sslm", corpus, pair["appended_token_id"], 263, len(corpus), "S", verdict)
    except Exception as ex:  # noqa: BLE001
        verdict(False, "S synthetic pair arms", f"{type(ex).__name__}: {ex}")

    if not args.model:
        verdict(True, "R real candidate arms", "no --model / SEMB_C12B_MODEL given; the 633 MB artifact is never committed",
                missing=True)
    elif not Path(args.model).exists():
        verdict(False, "R real candidate arms", f"--model {args.model} does not exist")
    else:
        try:
            corpus = read_corpus(REAL_CORPUS)
            if args.limit:
                corpus = corpus[:args.limit]
            run_arms(inst, Path(args.model), corpus, CANDIDATE_APPEND_ID, CANDIDATE_WRONG_ID, args.omitted_rows, "R", verdict)
        except Exception as ex:  # noqa: BLE001
            verdict(False, "R real candidate arms", f"{type(ex).__name__}: {ex}")

    print("\nu1_trailing_special_mutants_check summary:")
    for cell, state, _ in rows:
        print(f"  {state:22s} {cell}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
