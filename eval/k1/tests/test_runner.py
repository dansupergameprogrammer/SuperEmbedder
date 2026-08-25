"""Tests for runner.py's own logic that isn't already covered as a scoring or guard
concern -- the smoke-query selection helper and the qrels-scoping fix, at unit scale (no
GPU, no network). The real end-to-end proof is the executed smoke run filed in the build
log (Claude/Brunel/u-k1-instrument-build-2026-08-25.md)."""
from __future__ import annotations

from eval.k1.runner import _select_smoke_queries, _build_qrels_by_query


def test_build_qrels_by_query_groups_rows():
    rows = [
        {"query-id": "q1", "corpus-id": "d1", "score": 1.0},
        {"query-id": "q1", "corpus-id": "d2", "score": 0.0},
        {"query-id": "q2", "corpus-id": "d3", "score": 2.0},
    ]
    grouped = _build_qrels_by_query(rows)
    assert grouped == {"q1": {"d1": 1.0, "d2": 0.0}, "q2": {"d3": 2.0}}


def test_select_smoke_queries_keeps_only_queries_with_a_surviving_relevant_doc():
    test_query_ids = ["q1", "q2", "q3"]
    qrels_by_query = {
        "q1": {"d1": 1.0},  # d1 survives truncation -> kept
        "q2": {"d99": 1.0},  # d99 does not survive -> dropped
        "q3": {"d2": 0.0, "d3": 1.0},  # d3 survives and is positively judged -> kept
    }
    truncated_corpus_ids = {"d1", "d2", "d3"}
    kept = _select_smoke_queries(test_query_ids, qrels_by_query, truncated_corpus_ids)
    assert kept == ["q1", "q3"]


def test_select_smoke_queries_drops_a_query_whose_only_relevant_doc_is_score_zero():
    test_query_ids = ["q1"]
    qrels_by_query = {"q1": {"d1": 0.0}}  # judged but not positively relevant
    kept = _select_smoke_queries(test_query_ids, qrels_by_query, {"d1"})
    assert kept == []
