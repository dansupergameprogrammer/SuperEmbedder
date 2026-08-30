"""Tests for ``eval/k1/tools/mint_anchors.py`` (TE-40 code review, Finding F-6 (Significant),
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree).

``anchors.py::TASKS``/``DESIGN_EXPECTED_NDCG10`` carried only the original four sets;
``mint_anchors.py::main()`` fetched that four-task default and passed it to
``write_anchors``, which rewrites the file whole (no merge, unlike ``mint_sets_lock.py``).
Executed (review Section 4.8): the committed ``anchors.json`` before had five keys; running
`main()`'s exact fetch-and-write sequence against it left four -- SCIDOCS's anchor silently
deleted, exit 0, no warning. These tests exercise the real ``main()`` entry point against a
tmp-path copy of ``ANCHORS_PATH`` (monkeypatched), with the network fetch stubbed (no live
HTTP call), so the real merge logic runs and only the network boundary is faked.
"""
from __future__ import annotations

import json
from pathlib import Path

import eval.k1.tools.mint_anchors as mod
from eval.k1.anchors import AnchorEntry


def _entry(key: str, ndcg: float) -> AnchorEntry:
    return AnchorEntry(
        metric="ndcg_at_10", task=key, model_name="BAAI/bge-small-en-v1.5",
        model_revision="deadbeef", ndcg_at_10=ndcg,
        source_url="https://example.invalid", fetch_date="2026-08-30",
        dataset_sha="fbfca6f624278ab416ede77e17cd91466113178c",
    )


def test_a_bare_rerun_no_longer_drops_an_existing_anchor_the_fetch_did_not_touch(tmp_path, monkeypatch):
    """The exact defect Poirot's review executed: an existing five-entry file, a bare re-run
    that only re-fetches the (now five-task) default. Before the fix this test would need a
    four-task default to reproduce the drop; after the fix, TASKS itself carries all five, so
    the merge path is exercised by having the fetch return fewer than the file holds --
    proving the merge, not merely the widened default, is what protects a partial fetch."""
    anchors_path = tmp_path / "anchors.json"
    anchors_path.write_text(json.dumps({
        "schema_version": 1,
        "reference": {
            "scifact": {"ndcg_at_10": 0.71273, "task": "SciFact"},
            "nfcorpus": {"ndcg_at_10": 0.34264, "task": "NFCorpus"},
            "fiqa": {"ndcg_at_10": 0.40343, "task": "FiQA2018"},
            "arguana": {"ndcg_at_10": 0.60348, "task": "ArguAna"},
            "scidocs": {"ndcg_at_10": 0.20518, "task": "SCIDOCS"},
        },
        "bm25": {"note": "n/a"},
    }), encoding="utf-8")
    monkeypatch.setattr(mod, "ANCHORS_PATH", anchors_path)

    # Stub the fetch to the design's own four-task table (simulates a fetch call that, for
    # whatever reason, only returns a subset of TASKS -- the merge must protect the rest).
    monkeypatch.setattr(mod, "mint_anchors", lambda: {
        "scifact": _entry("scifact", 0.71273),
        "nfcorpus": _entry("nfcorpus", 0.34264),
        "fiqa": _entry("fiqa", 0.40343),
        "arguana": _entry("arguana", 0.60348),
    })

    mod.main()

    written = json.loads(anchors_path.read_text(encoding="utf-8"))
    assert set(written["reference"].keys()) == {"scifact", "nfcorpus", "fiqa", "arguana", "scidocs"}
    assert written["reference"]["scidocs"]["ndcg_at_10"] == 0.20518


def test_default_tasks_now_includes_scidocs():
    """The direct cause the review named: TASKS lacked a 'scidocs' entry, so even a fetch of
    the full default silently omitted it."""
    from eval.k1.anchors import DESIGN_EXPECTED_NDCG10, TASKS

    assert "scidocs" in TASKS
    assert TASKS["scidocs"] == "SCIDOCS"
    assert DESIGN_EXPECTED_NDCG10["scidocs"] == 0.20518
