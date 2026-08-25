"""Tests for component 5 -- anchors.json. Pins the committed file (produced by an executed
fetch, build log) against the design's own Section 4.1 published table, so a future edit
that silently drifts from either the design or the real mteb/results source is caught."""
from __future__ import annotations

from pathlib import Path

from eval.k1.anchors import DESIGN_EXPECTED_NDCG10, read_anchors

ANCHORS_PATH = Path(__file__).resolve().parents[1] / "anchors.json"


def test_committed_anchors_reproduce_the_design_table():
    payload = read_anchors(ANCHORS_PATH)
    reference = payload["reference"]
    for key, expected in DESIGN_EXPECTED_NDCG10.items():
        assert reference[key]["ndcg_at_10"] == expected, key
        assert reference[key]["model_name"] == "BAAI/bge-small-en-v1.5"
        assert reference[key]["dataset_sha"] == "fbfca6f624278ab416ede77e17cd91466113178c"


def test_fiqa_anchor_carries_the_external_revision_flag():
    """Design Section 4.1: the FiQA-2018 row carries model_revision 'external', a weaker
    anchor than the other three -- this must survive into the committed file, not be
    silently normalized away."""
    payload = read_anchors(ANCHORS_PATH)
    assert payload["reference"]["fiqa"]["model_revision"] == "external"
    for key in ("scifact", "nfcorpus", "arguana"):
        assert payload["reference"][key]["model_revision"] == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"


def test_bm25_anchor_is_explicitly_absent_not_fabricated():
    payload = read_anchors(ANCHORS_PATH)
    assert "note" in payload["bm25"]
    assert "score" not in payload["bm25"]
