#!/usr/bin/env python3
"""Mints SCIDOCS's ``sets.lock`` entry and anchor -- TE-39 stage (b).

Design reference: ``te33-k1-gate-design-2026-08-25.md`` Section 16 (the amendment that adds
SCIDOCS as the publishable-set substitute for NFCorpus and FiQA-2018 on Run 1's public row,
ruled D-SLM4705/D-SLM4686). SCIDOCS is not pinned and has no anchor before this script runs.

Reuses the same fetch code paths ``mint_sets_lock.py`` and ``mint_anchors.py`` use for the
other four sets (``eval.k1.sets_lock._fetch_one_set``, ``eval.k1.anchors.mint_anchors``)
rather than duplicating the fetch logic. At the time this script was written (TE-39 stage
(b)), ``eval.k1.sets_lock.SET_REGISTRY`` did not yet carry SCIDOCS's repo id, so this script
supplied it directly (``SCIDOCS_REPO`` below); TE-40 has since added SCIDOCS to
``SET_REGISTRY`` itself, so this script's own hardcoded ``SCIDOCS_REPO`` is now redundant with
the registry rather than filling a gap in it -- both name the same repo id
(``mteb/scidocs``), and this script's real remaining purpose is the design-figure cross-check
below (Section 16's stated counts and anchor, checked rather than trusted) and the
license/anchor write that ``mint_sets_lock.py`` alone does not perform for any set. License is
not fetched by either existing tool for any set (Section 2.4 routes that to the deriver):
SCIDOCS's CC BY 4.0 was already derived at primary source and filed in the design's own
Section 16, so it is written in directly, the same way TE-39 stage (a) wrote the other four
sets' Linnaeus-derived license strings into ``sets.lock.json`` by hand rather than by a fetch.

Design Section 16's own stated figures are the check, not the input: 25,657 corpus documents,
1,000 test queries, 29,928 qrels rows, published bge-small-en-v1.5 nDCG@10 of 0.20518. If the
mint disagrees with any of these, this script stops and reports the discrepancy rather than
writing anything -- per the brief, the design's number is not reconciled to the mint's.

Usage:
    py -3.13 eval/k1/tools/mint_scidocs.py
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1.anchors import mint_anchors
from eval.k1.sets_lock import _fetch_one_set, read_sets_lock, write_sets_lock

SCIDOCS_REPO = "mteb/scidocs"
LOCK_PATH = Path(__file__).resolve().parents[1] / "sets.lock.json"
ANCHORS_PATH = Path(__file__).resolve().parents[1] / "anchors.json"

# Design Section 16's own stated figures -- the check, not the input.
EXPECTED_CORPUS_DOCS = 25657
EXPECTED_TEST_QUERIES = 1000
EXPECTED_QRELS_ROWS = 29928
EXPECTED_NDCG10 = 0.20518

# Derived at primary source, design Section 16: the repository's own LICENSE file at current
# HEAD, confirmed CC BY 4.0 by its own opening line, superseding BEIR paper Appendix E's
# stale GPLv3 citation (the maintainer re-licensed twice on 2022-10-28).
SCIDOCS_LICENSE = "CC BY 4.0"
SCIDOCS_LICENSE_SOURCE = (
    "https://github.com/allenai/scidocs/blob/main/LICENSE (fetched at current HEAD; "
    "supersedes the BEIR paper's stale GPLv3 citation -- design Section 16, D-SLM4705)"
)


def main() -> None:
    hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))

    print("Fetching SCIDOCS sets.lock entry (corpus, queries, test qrels)...")
    entry = _fetch_one_set("scidocs", SCIDOCS_REPO, hf_home)
    entry.license = SCIDOCS_LICENSE
    entry.license_source = SCIDOCS_LICENSE_SOURCE
    entry.license_derived = True

    lock_checks = [
        ("corpus_docs", entry.corpus_docs, EXPECTED_CORPUS_DOCS),
        ("queries_test", entry.queries_test, EXPECTED_TEST_QUERIES),
        ("qrels_test_rows", entry.qrels_test_rows, EXPECTED_QRELS_ROWS),
    ]
    for name, actual, expected in lock_checks:
        print(f"  {name}: fetched={actual} design={expected} "
              f"{'OK' if actual == expected else 'MISMATCH'}")
    lock_mismatches = [(n, a, e) for n, a, e in lock_checks if a != e]
    if lock_mismatches:
        print("DISCREPANCY -- SCIDOCS's fetched sets.lock figures do not match design Section 16:")
        for name, actual, expected in lock_mismatches:
            print(f"  {name}: fetched={actual} design={expected}")
        print("Per the brief: stop and report the discrepancy; do not reconcile it to the design.")
        sys.exit(1)

    print("Fetching SCIDOCS anchor (bge-small-en-v1.5 published nDCG@10, mteb/results)...")
    anchors = mint_anchors(tasks={"scidocs": "SCIDOCS"})
    scidocs_anchor = anchors["scidocs"]
    delta = abs(scidocs_anchor.ndcg_at_10 - EXPECTED_NDCG10)
    print(f"  scidocs: fetched={scidocs_anchor.ndcg_at_10} expected={EXPECTED_NDCG10} "
          f"delta={delta} revision={scidocs_anchor.model_revision}")
    if delta > 1e-6:
        print("DISCREPANCY -- SCIDOCS's fetched anchor does not reproduce design Section 16's "
              "published value.")
        print("Per the brief: stop and report the discrepancy; do not reconcile it to the design.")
        sys.exit(1)

    existing_lock = read_sets_lock(LOCK_PATH) if LOCK_PATH.exists() else {}
    existing_lock["scidocs"] = entry
    write_sets_lock(existing_lock, LOCK_PATH)
    print(f"written {LOCK_PATH} (scidocs entry added, {len(existing_lock)} sets total)")

    anchors_payload = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    anchors_payload.setdefault("reference", {})["scidocs"] = dataclasses.asdict(scidocs_anchor)
    ANCHORS_PATH.write_text(json.dumps(anchors_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"written {ANCHORS_PATH} (scidocs anchor added)")

    print("ALL SCIDOCS FIGURES MATCH DESIGN SECTION 16. sets.lock.json and anchors.json updated.")


if __name__ == "__main__":
    main()
