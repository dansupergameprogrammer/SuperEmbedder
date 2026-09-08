"""tests/c12b_epoch_store_cross_check.py -- TE-180 item 4 (D-SLM6430): the
epoch store's committed row-digest.tsv/lineage.tsv entries, for every real
document, against tests/c12b_row_digest_check.py's own instrument
(semb_c12b_row_digest) -- mechanizing the manual cross-check
`Claude/Brunel/te164-slice3-build-2026-09-07.md` sec 3 and
`Claude/Curie/te168-slice3-oracle-fix-2026-09-07.md` sec 3 both report as
an executed, one-off probe (5 real documents, byte-for-byte agreement) --
the comparison that caught and confirmed TE-168's fix to a two-round
vector-oracle defect (D-SLM6382/D-SLM6389). This cell is a registered
`real_artifact` cell, independent of both `epoch_store_emit`'s own
construction and of `tests/c2_lineage_equality_test.cpp`'s own oracle (C2).

THE COMPARISON, derived at source rather than assumed
(`StandardsDocument.md` sec 5.4, "a comparison is evidence only if both
sides are the same quantity"). `tests/semb_epoch_store_contract.h`'s own
header comment states, in the same sentences that fix the store's on-disk
shape, which of `c12b_row_digest_check.py`'s own three columns (seam_sha256,
psn_selected_sha256, psn_vector_sha256 -- that script's own docstring)
each store member's digest actually is:

  - row-digest.tsv's per-document digest IS c12b's own `psn_vector_sha256`
    column -- "the same definition tests/c12b_row_digest_check.py's own
    psn_vector_sha256 column carries" (semb_epoch_store_contract.h:37-42).
    Both are SHA-256 over the float32 vector bytes PS-N emits for that
    document -- what a user receives.
  - lineage.tsv's per-document digest IS c12b's own `seam_sha256` column,
    NOT `psn_selected_sha256` -- lineage.tsv holds SHA-256 over
    `semb_seam_serialize_document`'s bytes for EVERY position of the
    document (position 0 included, the appended end token included,
    PRE-final-norm), "the same column tests/c12b_row_digest_check.py's own
    instrument already emits under this exact name" (semb_epoch_store_
    contract.h:43-56). `psn_selected_sha256` is a DIFFERENT quantity (the
    serialisation of the ONE position PS-N selects, AFTER final norm) and
    is not compared here: TE-164 sec 3's own text names it beside
    `psn_vector_sha256` in one sentence, but the comparison it actually
    reports executing is against `vectors.f32`'s own bytes -- the same
    quantity row-digest.tsv's own digest already covers -- and neither
    that record nor TE-168 sec 3 compares `psn_selected_sha256` against
    anything the store commits. Comparing it to lineage.tsv would be the
    shared-parameter species this project's own standards name (grading
    two different quantities as though they were one): lineage.tsv is
    pre-final-norm and spans every position; psn_selected_sha256 is
    post-final-norm and spans one.

Both sides are computed independently: this cell takes NO input from
`tools/epoch-store/mint.cpp` (the store's own minting tool, read-only to
this seat and not imported) and NO input from `tests/
c2_lineage_equality_test.cpp`'s own oracle -- the same independence bar
`Claude/Bach/briefs/te162-slice3-red.md` sec 6 (TE-162 sec 6) states for C2
against `c12b_row_digest_check.py`, applied here to the opposite pairing
(the store's own committed bytes against c12b's own instrument) so this
comparison does not reintroduce the circularity that bar exists to
prevent.

THE INSTRUMENT is run directly (`semb_c12b_row_digest`), never through
`c12b_row_digest_check.py`'s own harness -- that script grades the
instrument's OWN internal consistency (S1-S5, R1); this cell grades the
STORE against the instrument's output, a different question, with the
identical configuration `c12b_row_digest_check.py`'s own R1 leg and
`tools/epoch-store/mint.cpp`'s own real leg both use (the chunk-batched
leg, whole-document chunk budget, PS-N last-position selection -- the
instrument's own defaults, passed explicitly by neither script nor this
one).

USAGE
  c12b_epoch_store_cross_check.py --instrument <semb_c12b_row_digest exe>
    --model <.sslm> --corpus <tokens.tsv> --append-token-id <n>
    --store-root <dir> --build-dir <scratch dir>

THE LIVE ENTRY GRADED (TE-190 item 5, D-SLM6466 ruling 2, closing O2): NOT
a caller-pinned fingerprint literal. `--corpus`'s own document count is
read first (cheap: no subprocess), then
`epoch_store_contract.select_live_fingerprint_by_document_count` picks the
single `epoch-store/live/<fingerprint>/` entry whose committed
row-digest.tsv carries that many documents, refusing by name -- before the
instrument is ever run -- when zero or more than one live entry matches.
A literal fingerprint false-reds this cell on a legitimate epoch rotation
(a second live entry committed alongside the graded one) for a reason
unrelated to the claim this cell grades; selecting by the corpus's own
shape does not.

Exit codes: 0 every document's row-digest.tsv AND lineage.tsv digest
matches c12b's own psn_vector_sha256/seam_sha256 columns for that
document; 1 any mismatch (named), any document present on one side only
(a named FAIL, never silently skipped), the live entry to grade could not
be selected (named, per the paragraph above), or the instrument absent
(red-unimplemented, printed by name -- never a silent MISSING
PREREQUISITE standing in for a comparison that did not run).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epoch_store_contract as contract  # noqa: E402

# label -> (seam_sha256, psn_selected_sha256, psn_vector_sha256)
C12bRow = Tuple[str, str, str]


def run_instrument(instrument: str, model: str, corpus: str, append_id: int, out_path: Path) -> Dict[str, C12bRow]:
    """Runs semb_c12b_row_digest once over the whole corpus -- chunk-batched
    leg, whole-document chunk budget, PS-N last-position selection (the
    instrument's own defaults) -- the SAME configuration `tests/
    c12b_row_digest_check.py`'s own R1 leg and `tools/epoch-store/mint.cpp`'s
    own real leg both use. Parses the instrument's own five-column TSV
    (`# semb_c12b_row_digest rows: label\\tn_positions\\tseam_sha256\\t
    psn_selected_sha256\\tpsn_vector_sha256\\t...`) into {document id:
    (seam_sha256, psn_selected_sha256, psn_vector_sha256)}."""
    cmd = [instrument, "--model", model, "--corpus", corpus, "--out", str(out_path),
           "--append-token-id", str(append_id)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"semb_c12b_row_digest exited {proc.returncode}: {proc.stdout}\n{proc.stderr}")
    rows: Dict[str, C12bRow] = {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            raise RuntimeError(f"malformed instrument row: {line[:100]!r}")
        label, _n_positions, seam_sha256, psn_selected_sha256, psn_vector_sha256 = parts[:5]
        if label in rows:
            raise RuntimeError(f"duplicate label in instrument output: {label!r}")
        rows[label] = (seam_sha256, psn_selected_sha256, psn_vector_sha256)
    if not rows:
        raise RuntimeError(f"instrument wrote no rows to {out_path}")
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instrument", default="", help="path to semb_c12b_row_digest; empty/absent = red-unimplemented")
    p.add_argument("--model", required=True, help="the real Qwen3-Embedding-0.6B .sslm (SEMB_C12B_MODEL)")
    p.add_argument("--corpus", required=True, help="the tokens.tsv naming every document to grade (corpus-239.tokens.tsv)")
    p.add_argument("--append-token-id", type=int, required=True)
    p.add_argument("--store-root", required=True,
                    help="the repository root whose epoch-store/live/<fingerprint>/ subtree holds the committed "
                         "entry (epoch_store_contract.LIVE_DIR already carries the 'epoch-store/live' prefix); "
                         "the entry graded is SELECTED by document count against --corpus, never pinned")
    p.add_argument("--build-dir", required=True)
    args = p.parse_args()

    if not args.instrument or not Path(args.instrument).exists():
        print("c12b_epoch_store_cross_check: RED -- the instrument (semb_c12b_row_digest) is not built. "
              "This is red-unimplemented, not a verified pass.")
        return 1

    store_root = Path(args.store_root)

    # TE-190 item 5: select the live entry to grade BEFORE the (expensive)
    # instrument run -- cheap (no subprocess), and lets a refusal report by
    # name without paying for a real leg that was never going to be graded
    # against anything.
    corpus_docs = contract.read_tokens_tsv(Path(args.corpus))
    expected_document_count = len(corpus_docs)
    try:
        fingerprint = contract.select_live_fingerprint_by_document_count(store_root, expected_document_count)
    except ValueError as ex:
        print(f"[FAIL] (setup) selecting the live entry to grade against --corpus's {expected_document_count} "
              f"document(s): {ex}")
        return 1

    scratch = Path(args.build_dir) / "_c12b_epoch_store_cross_check"
    scratch.mkdir(parents=True, exist_ok=True)
    out_path = scratch / "rows.tsv"

    try:
        c12b_rows = run_instrument(args.instrument, args.model, args.corpus, args.append_token_id, out_path)
    except Exception as ex:  # noqa: BLE001 -- any setup failure is a named FAIL, never a silent skip
        print(f"[FAIL] (setup) semb_c12b_row_digest: {ex}")
        return 1

    entry_dir = contract.entry_dir(store_root, contract.LIVE_DIR, fingerprint)
    row_digest_path = entry_dir / contract.ROW_DIGEST_FILE_NAME
    lineage_path = entry_dir / contract.LINEAGE_FILE_NAME
    try:
        row_digest_per_doc, _row_digest_all = contract.parse_row_digest_tsv(row_digest_path.read_text(encoding="utf-8"))
        lineage_per_doc, _lineage_all = contract.parse_lineage_tsv(lineage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        print(f"[FAIL] (setup) reading the committed store entry at {entry_dir}: {ex}")
        return 1

    all_ids = sorted(set(c12b_rows) | set(row_digest_per_doc) | set(lineage_per_doc))
    failures: List[str] = []
    for doc_id in all_ids:
        if doc_id not in c12b_rows:
            print(f"[FAIL] {doc_id}: no semb_c12b_row_digest row for this document "
                  "(present in the committed store only)")
            failures.append(doc_id)
            continue
        seam_sha256, _psn_selected_sha256, psn_vector_sha256 = c12b_rows[doc_id]
        if doc_id not in row_digest_per_doc:
            print(f"[FAIL] {doc_id}: no row-digest.tsv entry for this document "
                  "(present in semb_c12b_row_digest's own output only)")
            failures.append(doc_id)
            continue
        if doc_id not in lineage_per_doc:
            print(f"[FAIL] {doc_id}: no lineage.tsv entry for this document "
                  "(present in semb_c12b_row_digest's own output only)")
            failures.append(doc_id)
            continue
        store_row_digest = row_digest_per_doc[doc_id]
        store_lineage = lineage_per_doc[doc_id]
        row_ok = store_row_digest == psn_vector_sha256
        lineage_ok = store_lineage == seam_sha256
        if not row_ok:
            print(f"[FAIL] {doc_id}: row-digest.tsv={store_row_digest} != "
                  f"semb_c12b_row_digest psn_vector_sha256={psn_vector_sha256}")
            failures.append(doc_id)
        if not lineage_ok:
            print(f"[FAIL] {doc_id}: lineage.tsv={store_lineage} != "
                  f"semb_c12b_row_digest seam_sha256={seam_sha256}")
            if row_ok:
                failures.append(doc_id)
        if row_ok and lineage_ok:
            print(f"[PASS] {doc_id}: row-digest.tsv == psn_vector_sha256; lineage.tsv == seam_sha256")

    print(f"\nc12b_epoch_store_cross_check: {len(all_ids)} document(s), {len(failures)} failure(s): {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
