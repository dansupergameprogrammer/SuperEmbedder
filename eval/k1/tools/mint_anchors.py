#!/usr/bin/env python3
"""Re-runs the fetch that produces ``eval/k1/anchors.json``. Executed 2026-08-25; all four
fetched values reproduced te33-k1-gate-design-2026-08-25.md Section 4.1's published table
exactly (delta 0.0 on every set) -- see the build log for the run's console output.

Usage:
    py -3.13 eval/k1/tools/mint_anchors.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1.anchors import DESIGN_EXPECTED_NDCG10, mint_anchors, write_anchors

ANCHORS_PATH = Path(__file__).resolve().parents[1] / "anchors.json"


def main() -> None:
    anchors = mint_anchors()
    mismatches = []
    for key, entry in anchors.items():
        expected = DESIGN_EXPECTED_NDCG10.get(key)
        delta = abs(entry.ndcg_at_10 - expected) if expected is not None else None
        print(f"{key}: fetched={entry.ndcg_at_10} expected={expected} delta={delta} "
              f"revision={entry.model_revision}")
        if expected is not None and delta > 1e-6:
            mismatches.append((key, entry.ndcg_at_10, expected, delta))
    if mismatches:
        print("DISCREPANCY -- fetched value(s) do not reproduce the design's table:")
        for key, fetched, expected, delta in mismatches:
            print(f"  {key}: fetched={fetched} design={expected} delta={delta}")
        print("Per the build brief: stop and file the discrepancy rather than proceed.")
        sys.exit(1)
    write_anchors(
        anchors, ANCHORS_PATH,
        bm25_note=(
            "Published per-task BM25 nDCG@10 not fetched -- no stable BM25 model entry "
            "exists in mteb/results (spec gap G-4, build log). F2 uses the local BM25 run "
            "directly."
        ),
    )
    print(f"ALL {len(anchors)} ANCHORS REPRODUCED THE DESIGN TABLE. written {ANCHORS_PATH}")


if __name__ == "__main__":
    main()
