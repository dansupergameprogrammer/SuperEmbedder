"""Tests for component 6 -- the BM25 baseline."""
from __future__ import annotations

import pytest

from eval.k1.guards import K1GuardError
from eval.k1.bm25_baseline import bm25_topk, build_bm25_index


def _toy_corpus():
    return [
        {"_id": "d1", "title": "Cats", "text": "Cats are small feline mammals that purr."},
        {"_id": "d2", "title": "Dogs", "text": "Dogs are loyal canine mammals that bark."},
        {"_id": "d3", "title": "Rockets", "text": "Rockets use combustion to reach orbit."},
    ]


def test_bm25_ranks_lexically_relevant_doc_first():
    corpus = _toy_corpus()
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "small feline mammals"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    assert run["q1"][0][0] == "d1"


def test_bm25_refuses_missing_params():
    corpus = _toy_corpus()
    with pytest.raises(K1GuardError) as exc:
        build_bm25_index(corpus, k1=None, b=None, set_name="unit")
    assert exc.value.code == "K1_BM25_PARAMS_MISSING"


def test_bm25_ties_break_by_ascending_corpus_id():
    corpus = [
        {"_id": "c", "title": "", "text": "same same same"},
        {"_id": "a", "title": "", "text": "same same same"},
        {"_id": "b", "title": "", "text": "same same same"},
    ]
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "same"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    assert [docid for docid, _s in run["q1"]] == ["a", "b", "c"]
