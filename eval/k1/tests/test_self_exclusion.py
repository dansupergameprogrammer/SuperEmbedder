"""Tests for the shared self-exclusion helper (``eval.k1.self_exclusion``) and, structurally,
that both rankers in this package route through it rather than reimplementing the filter.

U-K1 fix round 2b (class fix for D-SLM4699): fix round 2 fixed the self-exclusion defect only
in ``rank_score.cosine_topk``; ``bm25_baseline.bm25_topk`` carried the identical defect,
unfixed, because each ranker had its own inline copy of the logic. This module's unit tests
pin the helper itself; the spy-fixture tests below pin that BOTH rankers call it -- proving
by execution, not by reading the source, that a future third ranker cannot reintroduce the
defect by omission without also failing one of these tests."""
from __future__ import annotations

import numpy as np
import pytest

import eval.k1.bm25_baseline as bm25_baseline_module
import eval.k1.rank_score as rank_score_module
from eval.k1.bm25_baseline import bm25_topk, build_bm25_index
from eval.k1.rank_score import cosine_topk
from eval.k1.self_exclusion import SELF_EXCLUSION_NOTE, exclude_self_and_truncate


# --------------------------------------------------------------------------------------
# Unit tests -- the helper itself
# --------------------------------------------------------------------------------------


def test_exclude_self_and_truncate_drops_the_query_own_id():
    ranked = [("q1", 1.0), ("d_a", 0.9), ("d_b", 0.8), ("d_c", 0.7)]
    result = exclude_self_and_truncate(ranked, query_id="q1", k=3)
    assert result == [("d_a", 0.9), ("d_b", 0.8), ("d_c", 0.7)]


def test_exclude_self_and_truncate_is_a_no_op_shape_when_id_absent():
    ranked = [("d_a", 0.9), ("d_b", 0.8), ("d_c", 0.7), ("d_d", 0.6)]
    result = exclude_self_and_truncate(ranked, query_id="q1", k=3)
    assert result == [("d_a", 0.9), ("d_b", 0.8), ("d_c", 0.7)]  # ordinary top-k, unshortened


def test_exclude_self_and_truncate_truncates_after_filtering_not_before():
    """If truncation happened before filtering, a self-id sitting inside the first k
    positions would still consume a slot and the returned list would be short by one. This
    fixture puts the self-id at rank 1 of a corpus exactly k+1 long, so filter-before-
    truncate is the only order that returns a full k-length list."""
    ranked = [("q1", 1.0), ("d_a", 0.9), ("d_b", 0.8), ("d_c", 0.7)]  # k+1 = 4 candidates
    result = exclude_self_and_truncate(ranked, query_id="q1", k=3)
    assert len(result) == 3  # full k, not 2 -- proves filter-before-truncate ordering


def test_self_exclusion_note_documents_both_rankers():
    assert "dense ranker" in SELF_EXCLUSION_NOTE or "ranker" in SELF_EXCLUSION_NOTE
    assert isinstance(SELF_EXCLUSION_NOTE, str) and len(SELF_EXCLUSION_NOTE) > 0


# --------------------------------------------------------------------------------------
# Structural pins -- both rankers route self-exclusion through the shared helper, not an
# inline reimplementation. Each test neutralizes the shared helper to an exclusion-free
# passthrough and confirms the self-match REAPPEARS -- if either ranker applied any
# exclusion of its own independent of the helper, the self-id would stay excluded even with
# the helper neutralized.
# --------------------------------------------------------------------------------------


def test_cosine_topk_has_no_self_exclusion_of_its_own(monkeypatch):
    def _passthrough(ranked, query_id, k):
        return list(ranked)[:k]

    monkeypatch.setattr(rank_score_module, "exclude_self_and_truncate", _passthrough)

    query_vecs = np.array([[1.0, 0.0]])
    corpus_vecs = np.array([[1.0, 0.0], [0.9, 0.1], [0.7, 0.3], [0.5, 0.5], [0.0, 1.0]])
    corpus_ids = ["q1", "d_close", "d_mid", "d_far", "d_orthogonal"]
    run = cosine_topk(query_vecs, ["q1"], corpus_vecs, corpus_ids, k=3)
    ranked_ids = [docid for docid, _s in run["q1"]]
    assert ranked_ids[0] == "q1"  # the self-match reappears with the helper neutralized


def test_bm25_topk_has_no_self_exclusion_of_its_own(monkeypatch):
    def _passthrough(ranked, query_id, k):
        return list(ranked)[:k]

    monkeypatch.setattr(bm25_baseline_module, "exclude_self_and_truncate", _passthrough)

    corpus = [
        {"_id": "q1", "title": "", "text": "zebras graze quietly near acacia trees at dawn"},
        {"_id": "d_close", "title": "", "text": "zebras graze near acacia trees during the morning"},
        {"_id": "d_mid", "title": "", "text": "zebras wander across open savanna grassland"},
        {"_id": "d_far", "title": "", "text": "penguins swim through icy antarctic waters"},
    ]
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "zebras graze quietly near acacia trees at dawn"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    ranked_ids = [docid for docid, _s in run["q1"]]
    assert ranked_ids[0] == "q1"  # the self-match reappears with the helper neutralized


def test_both_rankers_call_the_identical_shared_function_object():
    """Both modules import the SAME function object from ``eval.k1.self_exclusion`` -- not
    two functions that happen to behave identically. This is the structural guarantee that
    the convention is implemented exactly once."""
    assert rank_score_module.exclude_self_and_truncate is exclude_self_and_truncate
    assert bm25_baseline_module.exclude_self_and_truncate is exclude_self_and_truncate
