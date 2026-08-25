"""Tests for component 3 (ranker + dual scorer): the deciding metric, R1's independent
scorer, the diagnostics, achieved resolving power, and executed chance."""
from __future__ import annotations

import math

import numpy as np
import pytest

from eval.k1.rank_score import (
    achieved_resolving_power,
    cosine_topk,
    executed_chance_level,
    mrr_at_k,
    ndcg_at_k_own,
    ndcg_at_k_pytrec,
    recall_at_k,
)


def _toy_problem():
    """3 queries, 5 corpus docs, binary qrels, and a hand-picked run whose nDCG@10 is
    computable by hand -- q1's ideal top-2 is [d1(1), d2(1)] and the run has [d3, d1, d2],
    so DCG = 0/log2(2) + 1/log2(3) + 1/log2(4) = 1.2925; IDCG = 1/log2(2)+1/log2(3)=1.6309;
    nDCG = 0.7925."""
    qrels = {
        "q1": {"d1": 1.0, "d2": 1.0},
        "q2": {"d3": 1.0},
        "q3": {"d4": 2.0, "d5": 1.0},
    }
    run = {
        "q1": [("d3", 0.9), ("d1", 0.8), ("d2", 0.5), ("d4", 0.1)],
        "q2": [("d3", 0.99), ("d1", 0.2)],
        "q3": [("d4", 0.7), ("d5", 0.6), ("d1", 0.1)],
    }
    return qrels, run


def test_ndcg_own_matches_hand_computation():
    qrels, run = _toy_problem()
    per_query, mean_ndcg = ndcg_at_k_own(qrels, run, k=10)
    expected_q1 = (1 / math.log2(3) + 1 / math.log2(4)) / (1 / math.log2(2) + 1 / math.log2(3))
    assert per_query["q1"] == pytest.approx(expected_q1, abs=1e-9)
    assert per_query["q2"] == pytest.approx(1.0, abs=1e-9)  # d3 at rank 1, ideal
    # q3 ideal: d4(2) rank1, d5(1) rank2 -> IDCG = 2/log2(2) + 1/log2(3)
    # run: d4 rank1 (gain2), d5 rank2 (gain1) -> DCG same as IDCG
    assert per_query["q3"] == pytest.approx(1.0, abs=1e-9)


def test_ndcg_own_agrees_with_pytrec_eval():
    """R1: the instrument's own scorer and the independent scorer must agree to 1e-6."""
    pytest.importorskip("pytrec_eval")
    qrels, run = _toy_problem()
    per_query_own, mean_own = ndcg_at_k_own(qrels, run, k=10)
    per_query_pytrec, mean_pytrec = ndcg_at_k_pytrec(qrels, run, k=10)
    for qid in qrels:
        assert per_query_own[qid] == pytest.approx(per_query_pytrec[qid], abs=1e-6), qid
    assert mean_own == pytest.approx(mean_pytrec, abs=1e-6)


def test_zero_idcg_query_scores_zero_not_an_exception():
    qrels = {"q1": {"d1": 0.0}}  # a qrels row that exists but carries no positive relevance
    run = {"q1": [("d1", 0.9)]}
    per_query, mean_ndcg = ndcg_at_k_own(qrels, run, k=10)
    assert per_query["q1"] == 0.0
    assert mean_ndcg == 0.0


def test_guard_removed_turns_the_emptied_join_green():
    """Coverage Model dimension 11's second half (design Section 11): with the zero-qrels
    guard's check removed from the call path, the scorer alone processes an emptied
    query-id/document-id join (the join a real id-column mismatch would produce) and
    reports a clean 0.0 -- a flattering, silent, wrong-looking-right number, not an
    exception. In the real pipeline (runner.py) ``guards.validate_qrels_join`` runs BEFORE
    this scoring path and would have raised K1_QRELS_EMPTY on this exact input, which is
    what makes the guard load-bearing rather than decorative."""
    qrels_by_query = {
        "q1": {"d1": 1.0, "d2": 1.0},
        "q2": {"d3": 1.0},
    }
    emptied_corpus_ids = {"zzz1", "zzz2", "zzz3"}  # disjoint from every qrels docid
    run = {qid: [(docid, 1.0) for docid in emptied_corpus_ids] for qid in qrels_by_query}
    per_query, mean_ndcg = ndcg_at_k_own(qrels_by_query, run, k=10)
    assert mean_ndcg == 0.0
    assert all(v == 0.0 for v in per_query.values())


def test_cosine_topk_ties_break_by_ascending_corpus_id():
    query_vecs = np.array([[1.0, 0.0]])
    corpus_vecs = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])  # all identical -> tie
    corpus_ids = ["c", "a", "b"]
    run = cosine_topk(query_vecs, ["q1"], corpus_vecs, corpus_ids, k=3)
    assert [docid for docid, _score in run["q1"]] == ["a", "b", "c"]


def test_cosine_topk_ranks_by_similarity():
    query_vecs = np.array([[1.0, 0.0]])
    corpus_vecs = np.array([[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]])
    corpus_ids = ["orthogonal", "identical", "diagonal"]
    run = cosine_topk(query_vecs, ["q1"], corpus_vecs, corpus_ids, k=3)
    assert [docid for docid, _s in run["q1"]] == ["identical", "diagonal", "orthogonal"]


def test_recall_and_mrr_diagnostics():
    qrels, run = _toy_problem()
    _per_q, mean_recall = recall_at_k(qrels, run, k=10)
    _per_q_mrr, mean_mrr = mrr_at_k(qrels, run, k=10)
    assert 0.0 <= mean_recall <= 1.0
    assert 0.0 <= mean_mrr <= 1.0


def test_achieved_resolving_power_shrinks_with_more_queries():
    rng = np.random.default_rng(0)
    small = {f"q{i}": v for i, v in enumerate(rng.normal(0.5, 0.2, size=10))}
    large = {f"q{i}": v for i, v in enumerate(rng.normal(0.5, 0.2, size=1000))}
    rp_small = achieved_resolving_power(small)
    rp_large = achieved_resolving_power(large)
    assert rp_large < rp_small


def test_executed_chance_level_is_near_zero_for_sparse_relevance():
    """A large corpus with exactly one relevant document per query should show chance near
    1/N-scale, far below any real system's nDCG@10 -- sanity-checks the Monte Carlo
    machinery against the analytic expectation design Section 4.4 tables."""
    corpus_ids = [f"d{i}" for i in range(2000)]
    qrels = {"q1": {"d0": 1.0}}
    result = executed_chance_level(qrels, ["q1"], corpus_ids, k=10, trials=500, seed=1)
    assert 0.0 <= result.mean < 0.02  # analytic expectation is ~10/2000 * harmonic-ish factor, small
