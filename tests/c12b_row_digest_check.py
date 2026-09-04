"""tests/c12b_row_digest_check.py -- C12b's cell: forward identity by per-row
byte digests (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C12b; D-SLM4648),
graded through ONE instrument (`semb_c12b_row_digest`, src/c12b/) over ONE
fixed corpus (tests/fixtures/c12b/corpus-239.tokens.tsv, minted by
tools/c12b/mint_c12b_corpus.py) on ONE artifact, emitting per-row SHA-256
over the emitted `{codes, m, e}` seam bytes -- never only an aggregate.

THREE COLUMNS PER ROW, so a red reading attributes by investigation rather
than by assumption (the plan's three attributions -- the forward moved, the
port is wrong, the entry-point substitution is not bit-identical):

  seam_sha256          SHA-256 over `semb_seam_serialize_document`'s bytes for
                       every position of the document (position 0 included,
                       the appended end token included) -- the W-B seam, the
                       forward's own output BEFORE any pooling.
  psn_selected_sha256  the same serialisation of the ONE position PS-N selects
                       (the last), AFTER the engine's final norm -- PS-N's
                       source state (sec 3.2: post-final-norm).
  psn_vector_sha256    SHA-256 over the float32 vector bytes PS-N emits from
                       that position (little-endian bit patterns) -- what a
                       user receives.

A seam column that moves is the forward or the port; a seam column that
holds while a PS-N column moves is the selection or the dequantize; the two
legs (`--leg chunk` against `--leg token`) disagreeing on the seam column is
the entry-point substitution. Each is a different suspect, and this file
never collapses them into one verdict.

CELLS (StandardsDocument.md sec 5.4: an instrument is commissioned before
its verdicts are load-bearing -- must-accept AND must-reject, both
producible by the instrument's real data path):

  S1 must-accept, determinism  two independent processes, every column of
                               every row byte-identical.
  S2 entry-point substitution  chunk-batched leg == per-token leg, per row,
                               all three columns (C12b's third attribution,
                               made executable rather than assumed).
  S3 chunk budget inert        budget 2 == whole-document budget, per row
                               (C40's claim, re-read through this instrument).
  S4 MUST-REJECT, wrong position  `--select second-last` -- PS-N's own
                               must-reject per sec 9 dim 10 ("a deliberately
                               wrong-position selection ... the second-to-last
                               token instead of the last, or an off-by-one
                               under right-padding/truncation"): the seam
                               column must be IDENTICAL (the forward did not
                               move) and BOTH PS-N columns must DIFFER on
                               EVERY row. A row where they agree is a dead
                               must-reject and fails this cell. This is not
                               PS-1's retired position-0 mutation.
  S5 C1' oracle                the instrument's dumped selected triple and
                               emitted bits agree with tests/oracle/
                               ps_n_reference.py (exact rational, no input
                               from the code under test), for BOTH selections.
  R1 the real workload         when `--model` names the real Qwen3-Embedding-
                               0.6B artifact: both legs over all 239 rows,
                               per-row S2 agreement, S5 on every real row, and
                               a per-row comparison against the committed
                               anchor table when one exists (`--anchors`);
                               `--mint-anchors` writes that table from the
                               chunk leg's rows. Without `--model` this leg
                               reports MISSING PREREQUISITE, named -- the
                               633 MB artifact is never committed.

S1-S5 run on the synthetic tiny artifact (hidden 32, vocab 128, context_cap
64) with tests/fixtures/c12b/synthetic-corpus.tokens.tsv and an in-vocab
appended token id (127) -- MECHANISM cells; R1 is the PRODUCT cell.

Exit codes: 0 every evaluated cell PASS (R1 may be MISSING PREREQUISITE);
1 any FAIL, or the instrument absent (red-unimplemented).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "c12b"
SYNTHETIC_CORPUS = FIXTURES / "synthetic-corpus.tokens.tsv"
REAL_CORPUS = FIXTURES / "corpus-239.tokens.tsv"
SYNTHETIC_APPEND_ID = 127          # in the synthetic fixture's 128-entry vocab
CANDIDATE_APPEND_ID = 151643       # <|endoftext|>, sec 3.2's PS-N position rule
ORACLE = REPO_ROOT / "tests" / "oracle" / "ps_n_reference.py"

Row = Tuple[int, str, str, str]  # n_positions, seam, psn_selected, psn_vector


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_synthetic_artifact() -> Path:
    path = REPO_ROOT / "build" / "_scratch" / "synthetic_te62_c39.sslm"
    if path.exists():
        return path
    cmd = [sys.executable, str(REPO_ROOT / "tests" / "fixtures" / "regenerate_synthetic_artifact.py"),
           "--lock", "superslm.lock", "--out", str(path)]
    src = os.environ.get("SEMB_TEST_ENGINE_SOURCE")
    if src:
        cmd += ["--source", src]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return path


class Instrument:
    def __init__(self, exe: Path, scratch: Path):
        self.exe = exe
        self.scratch = scratch
        scratch.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def run(self, model: Path, corpus: Path, append_id: int, leg: str = "chunk", budget: int = 0,
            select: str = "last", dump: Optional[Path] = None, tag: str = "") -> Tuple[Dict[str, Row], str, float]:
        self.calls += 1
        out = self.scratch / f"rows_{self.calls:03d}_{tag or leg}.tsv"
        cmd = [str(self.exe), "--model", str(model), "--corpus", str(corpus), "--out", str(out),
               "--leg", leg, "--chunk-budget", str(budget), "--select", select,
               "--append-token-id", str(append_id)]
        if dump is not None:
            cmd += ["--dump-selected", str(dump)]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        elapsed = time.perf_counter() - t0
        if proc.returncode != 0:
            raise RuntimeError(f"instrument exited {proc.returncode}: {' '.join(cmd)}\n"
                               f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        return parse_rows(out), proc.stdout, elapsed


def parse_rows(path: Path) -> Dict[str, Row]:
    rows: Dict[str, Row] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            raise RuntimeError(f"malformed instrument row: {line[:100]}")
        label, n, seam, sel, vec = parts[:5]
        if label in rows:
            raise RuntimeError(f"duplicate label in instrument output: {label}")
        rows[label] = (int(n), seam, sel, vec)
    if not rows:
        raise RuntimeError(f"instrument wrote no rows to {path}")
    return rows


def compare(a: Dict[str, Row], b: Dict[str, Row], cols: Tuple[int, ...]) -> List[str]:
    """Labels whose given columns differ (or that are missing on one side)."""
    diffs = []
    for label in sorted(set(a) | set(b)):
        if label not in a or label not in b:
            diffs.append(label)
            continue
        if any(a[label][c] != b[label][c] for c in cols):
            diffs.append(label)
    return diffs


def oracle_check(dump: Path) -> Tuple[bool, str]:
    proc = subprocess.run([sys.executable, str(ORACLE), "--check", str(dump)], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip().splitlines()[-1] if (proc.stdout + proc.stderr).strip() else ""


def read_anchors(path: Path) -> Dict[str, Row]:
    return parse_rows(path)


def write_anchors(path: Path, rows: Dict[str, Row], header: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for h in header:
            f.write("# " + h + "\n")
        f.write("# label\tn_positions\tseam_sha256\tpsn_selected_sha256\tpsn_vector_sha256\n")
        for label in rows:  # instrument order == corpus order
            n, seam, sel, vec = rows[label]
            f.write(f"{label}\t{n}\t{seam}\t{sel}\t{vec}\n")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instrument", default="", help="path to semb_c12b_row_digest; empty = not built (RED)")
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--model", default=os.environ.get("SEMB_C12B_MODEL", ""),
                    help="the real Qwen3-Embedding-0.6B .sslm (R1); env SEMB_C12B_MODEL")
    ap.add_argument("--anchors", default=str(FIXTURES / "anchors-qwen3-embedding-0.6b-v1.4.0.tsv"))
    ap.add_argument("--mint-anchors", action="store_true",
                    help="R1: write --anchors from the chunk leg's rows (a minting run, not a grading run)")
    ap.add_argument("--engine-pin", default="", help="R1 anchor header: the engine tag@commit this run built against")
    args = ap.parse_args(argv)

    if not args.instrument or not Path(args.instrument).exists():
        print("c12b_row_digest_check: RED -- the instrument (semb_c12b_row_digest) is not built. "
              "This is red-unimplemented, not a verified pass: the product entry points this cell "
              "grades (src/c12b/, the interim encoder handle, PS-N's selection and dequantize) do "
              "not exist yet.")
        return 1

    scratch = Path(args.build_dir) / "_c12b"
    inst = Instrument(Path(args.instrument), scratch)
    verdicts: List[Tuple[str, str, str]] = []  # (cell, PASS|FAIL|MISSING PREREQUISITE, observed)
    ok_all = True

    def verdict(cell: str, passed: Optional[bool], observed: str):
        nonlocal ok_all
        state = "MISSING PREREQUISITE" if passed is None else ("PASS" if passed else "FAIL")
        if passed is False:
            ok_all = False
        verdicts.append((cell, state, observed))
        print(f"[{state}] {cell}: {observed}")

    # ---- Mechanism cells on the synthetic artifact -----------------------------------------
    try:
        syn = ensure_synthetic_artifact()
    except Exception as ex:  # noqa: BLE001
        verdict("S0 synthetic artifact", False, f"could not regenerate: {ex}")
        return 1

    a1, out1, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, tag="s1a")
    a2, _, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, tag="s1b")
    d = compare(a1, a2, (0, 1, 2, 3))
    verdict("S1 must-accept: two processes byte-identical, all columns",
            not d, f"{len(a1)} rows; differing rows: {d or 'none'}")

    tok, _, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, leg="token", tag="s2tok")
    d = compare(a1, tok, (0, 1, 2, 3))
    verdict("S2 entry-point substitution: chunk-batched leg == per-token leg, per row",
            not d, f"differing rows: {d or 'none'}")

    b2, _, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, budget=2, tag="s3b2")
    d = compare(a1, b2, (0, 1, 2, 3))
    verdict("S3 chunk budget inert: budget 2 == whole document, per row",
            not d, f"differing rows: {d or 'none'}")

    dump_last = scratch / "dump_synthetic_last.tsv"
    dump_second = scratch / "dump_synthetic_second_last.tsv"
    last, _, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, dump=dump_last, tag="s4last")
    second, _, _ = inst.run(syn, SYNTHETIC_CORPUS, SYNTHETIC_APPEND_ID, select="second-last",
                            dump=dump_second, tag="s4second")
    seam_moved = compare(last, second, (1,))
    sel_same = [lb for lb in last if lb in second and last[lb][2] == second[lb][2]]
    vec_same = [lb for lb in last if lb in second and last[lb][3] == second[lb][3]]
    verdict("S4 MUST-REJECT: wrong position (second-to-last) -- seam identical, both PS-N columns differ on every row",
            not seam_moved and not sel_same and not vec_same,
            f"seam moved on: {seam_moved or 'none'}; selected column unchanged on: {sel_same or 'none'}; "
            f"vector column unchanged on: {vec_same or 'none'} ({len(last)} rows)")

    ok5a, msg5a = oracle_check(dump_last)
    ok5b, msg5b = oracle_check(dump_second)
    verdict("S5 C1' oracle: emitted bits == exact-rational dequantize of the dumped triple (both selections)",
            ok5a and ok5b, f"last: {msg5a}; second-last: {msg5b}")

    # ---- The real workload --------------------------------------------------------------------
    if not args.model:
        verdict("R1 real artifact (Qwen3-Embedding-0.6B, 239 rows, both legs)", None,
                "no --model / SEMB_C12B_MODEL given; the 633 MB artifact is never committed")
    elif not Path(args.model).exists():
        verdict("R1 real artifact", False, f"--model {args.model} does not exist")
    else:
        model = Path(args.model)
        dump_real = scratch / "dump_real_last.tsv"
        real_chunk, out_c, t_c = inst.run(model, REAL_CORPUS, CANDIDATE_APPEND_ID, dump=dump_real, tag="r1chunk")
        real_token, out_t, t_t = inst.run(model, REAL_CORPUS, CANDIDATE_APPEND_ID, leg="token", tag="r1token")
        summary_c = [ln for ln in out_c.splitlines() if ln.startswith("c12b:")]
        summary_t = [ln for ln in out_t.splitlines() if ln.startswith("c12b:")]
        print("\n".join(summary_c + summary_t))
        n_rows = len(real_chunk)
        d = compare(real_chunk, real_token, (0, 1, 2, 3))
        verdict(f"R1.a real: chunk-batched leg == per-token leg on all {n_rows} rows",
                n_rows == 239 and not d, f"rows={n_rows}; differing: {len(d)} ({d[:5]}); "
                                          f"wall chunk={t_c:.1f}s token={t_t:.1f}s")
        real_chunk2, _, _ = inst.run(model, REAL_CORPUS, CANDIDATE_APPEND_ID, tag="r1chunk2")
        d = compare(real_chunk, real_chunk2, (0, 1, 2, 3))
        verdict("R1.b real: second process byte-identical on every row", not d, f"differing: {d or 'none'}")
        ok5r, msg5r = oracle_check(dump_real)
        verdict("R1.c real: C1' oracle on every selected position", ok5r, msg5r)
        real_second, _, _ = inst.run(model, REAL_CORPUS, CANDIDATE_APPEND_ID, select="second-last", tag="r1second")
        seam_moved = compare(real_chunk, real_second, (1,))
        sel_same = [lb for lb in real_chunk if real_chunk[lb][2] == real_second[lb][2]]
        vec_same = [lb for lb in real_chunk if real_chunk[lb][3] == real_second[lb][3]]
        verdict("R1.d real MUST-REJECT: second-to-last selection moves both PS-N columns on every row, seam held",
                not seam_moved and not sel_same and not vec_same,
                f"seam moved: {len(seam_moved)}; selected unchanged: {len(sel_same)}; vector unchanged: {len(vec_same)}")
        anchors = Path(args.anchors)
        if args.mint_anchors:
            header = [
                "tests/fixtures/c12b/anchors-*.tsv -- C12b per-row anchors (sec 8, C12b; D-SLM4648): one row per",
                "corpus document, computed by semb_c12b_row_digest over tests/fixtures/c12b/corpus-239.tokens.tsv",
                "(appended token id 151643), chunk-batched leg, whole-document chunk budget, PS-N last-position",
                "selection, post-final-norm. NEVER hand-edited; re-minted only by this check's --mint-anchors.",
                f"artifact: {model.name} sha256={sha256_file(model)} bytes={model.stat().st_size}",
                f"engine pin: {args.engine_pin or '(not stated on the command line)'}",
                f"host: {os.environ.get('COMPUTERNAME') or (os.uname().nodename if hasattr(os, 'uname') else '?')}",
                f"minted: {time.strftime('%Y-%m-%d')}",
            ]
            write_anchors(anchors, real_chunk, header)
            verdict("R1.e anchors MINTED (a minting run grades nothing against them)", True, str(anchors))
        elif anchors.exists():
            anc = read_anchors(anchors)
            d_seam = compare(anc, real_chunk, (0, 1))
            d_sel = compare(anc, real_chunk, (2,))
            d_vec = compare(anc, real_chunk, (3,))
            verdict("R1.e real vs committed anchors, per row",
                    not d_seam and not d_sel and not d_vec,
                    f"anchor rows={len(anc)}; seam differs on {len(d_seam)} rows {d_seam[:5]}; "
                    f"selected differs on {len(d_sel)}; vector differs on {len(d_vec)} -- a seam move is the "
                    f"forward or the port (investigate: pin, artifact bytes, adapter); a PS-N-only move is the "
                    f"selection or the dequantize")
        else:
            verdict("R1.e real vs committed anchors", None, f"no anchor table at {anchors}; run with --mint-anchors")

    print("\nc12b_row_digest_check summary:")
    for cell, state, _ in verdicts:
        print(f"  {state:20s} {cell}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
