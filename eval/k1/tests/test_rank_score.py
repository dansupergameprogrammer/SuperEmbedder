"""Tests for component 3 (ranker + dual scorer): the deciding metric, R1's independent
scorer, the diagnostics, achieved resolving power, and executed chance."""
from __future__ import annotations

import math

import numpy as np
import pytest

from eval.k1.rank_score import (
    ChanceResult,
    achieved_resolving_power,
    chance_level_resolving_power,
    cosine_topk,
    executed_chance_level,
    mrr_at_k,
    ndcg_at_k_own,
    ndcg_at_k_pytrec,
    read_trec_run,
    recall_at_k,
    write_trec_run,
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


def _graded_tie_problem():
    """A deterministic, committed graded-relevance (0/1/2) fixture reproducing Finding B's
    exact defect shape (U-K1 fix round, 2026-08-25, D-SLM4689): an EXACT score tie in the
    top-k between a graded-relevant document and an irrelevant one. Before the fix,
    ``ndcg_at_k_own`` breaks such a tie by the input list's own order (matching
    ``cosine_topk``'s deterministic ascending-corpus-id convention), while ``pytrec_eval``'s
    ``RelevanceEvaluator`` received a plain ``{docid: score}`` dict and re-sorted ties with
    its own internal (undocumented) convention -- producing a real, measured 5.49e-4
    disagreement on NFCorpus, ~500x the 1e-6 replication threshold. Reproduced here on a tiny
    fixture: q1's rank 1/2 are an exact tie (score 0.7347) between a grade-2 relevant
    document (``d_rel``) and an irrelevant one (``d_irrelevant``), with ``d_rel`` first in
    the input order -- the same shape (grade-2 relevant document tied with an irrelevant one,
    relevant document first) measured on NFCorpus query PLAIN-3131 in the commissioning run."""
    qrels = {
        "q1": {"d_rel": 2.0, "d_other": 1.0},
        "q2": {"d_a": 1.0, "d_b": 2.0, "d_c": 0.0},
    }
    run = {
        "q1": [("d_rel", 0.7347), ("d_irrelevant", 0.7347), ("d_other", 0.6), ("d_x", 0.1)],
        "q2": [("d_b", 0.9), ("d_a", 0.8), ("d_c", 0.5)],
    }
    return qrels, run


def test_ndcg_own_agrees_with_pytrec_eval_on_graded_relevance_with_a_tie():
    """R1 pin (U-K1 fix round, 2026-08-25, Finding B / D-SLM4689): the instrument's own
    scorer and the independent pytrec_eval scorer must agree to 1e-6 on a fixture that
    includes graded (non-binary) relevance AND an exact score tie between a relevant and an
    irrelevant document -- the exact defect shape found on NFCorpus. Before the
    rank-preserving fix in ``ndcg_at_k_pytrec``, this fixture reproduces a real disagreement
    (q1's two scorers place the tied documents in opposite order); after the fix, both
    scorers read the identical order ``run`` already specifies and agree exactly."""
    pytest.importorskip("pytrec_eval")
    qrels, run = _graded_tie_problem()
    per_query_own, mean_own = ndcg_at_k_own(qrels, run, k=10)
    per_query_pytrec, mean_pytrec = ndcg_at_k_pytrec(qrels, run, k=10)
    for qid in qrels:
        assert per_query_own[qid] == pytest.approx(per_query_pytrec[qid], abs=1e-6), qid
    assert mean_own == pytest.approx(mean_pytrec, abs=1e-6)
    # q1's tie must be resolved in `run`'s own order (d_rel, the relevant document, ranked
    # ahead of d_irrelevant) by BOTH scorers -- confirms the fix reproduces `run`'s order
    # rather than a coincidental numeric match. Hand computation: DCG = 2/log2(2) + 0 +
    # 1/log2(4) = 2.5; IDCG = 2/log2(2) + 1/log2(3) = 2.63093; nDCG = 0.95023. If either
    # scorer instead placed d_irrelevant ahead of d_rel, DCG would be 0/log2(2) + 2/log2(3) +
    # 1/log2(4) = 1.7618, giving nDCG = 0.66968 -- a different, lower value that is what the
    # pre-fix disagreement actually looked like.
    expected_q1 = 2.5 / (2.0 / math.log2(2) + 1.0 / math.log2(3))
    assert per_query_own["q1"] == pytest.approx(expected_q1, abs=1e-9)
    assert per_query_pytrec["q1"] == pytest.approx(expected_q1, abs=1e-9)


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


def test_unscoped_qrels_dilutes_the_mean_over_the_wrong_population():
    """Regression for a bug caught at the bench during the U-K1 smoke run (build log): when
    a caller runs on a POPULATION SUBSET (e.g. a truncated corpus whose surviving queries
    are a strict subset of the full qrels' queries) and passes the scorer the FULL,
    unscoped qrels_by_query dict rather than one restricted to the queries actually ranked,
    every un-ranked query silently contributes a 0.0 to the mean -- diluting a perfect
    per-query score into a number that looks like a near-total miss. This test pins BOTH
    behaviours: the unscoped call IS diluted (documenting the failure shape so it is
    recognisable if seen again), and the scoped call recovers the true value. The real
    fix lives in runner.py, which scopes qrels_by_query to test_query_ids before calling
    any scoring function."""
    full_qrels = {f"q{i}": {"d0": 1.0} for i in range(100)}  # 100 queries in the full split
    full_qrels["q0"] = {"d0": 1.0}
    run = {"q0": [("d0", 0.9)]}  # only q0 was actually ranked (e.g. a truncated corpus run)

    _per_q_unscoped, mean_unscoped = ndcg_at_k_own(full_qrels, run, k=10)
    assert mean_unscoped == pytest.approx(1.0 / 100, abs=1e-9)  # diluted -- the bug shape

    scoped_qrels = {"q0": full_qrels["q0"]}
    _per_q_scoped, mean_scoped = ndcg_at_k_own(scoped_qrels, run, k=10)
    assert mean_scoped == pytest.approx(1.0, abs=1e-9)  # correct once scoped


def test_trec_run_file_round_trips(tmp_path):
    """The commissioning spec's must-reject 2 (Mendeleev's construction 3.3) reuses
    construction 3.1's already-computed TREC run file rather than re-embedding -- this
    round-trip is what makes that reuse possible."""
    _qrels, run = _toy_problem()
    path = tmp_path / "run.trec"
    write_trec_run(run, path, run_name="unit-test")
    loaded = read_trec_run(path)
    assert set(loaded.keys()) == set(run.keys())
    for qid in run:
        assert [docid for docid, _s in loaded[qid]] == [docid for docid, _s in run[qid]]
        for (_, orig_score), (_, loaded_score) in zip(run[qid], loaded[qid]):
            assert loaded_score == pytest.approx(orig_score, abs=1e-6)


def test_chance_level_resolving_power_is_the_single_trial_spread_not_the_mean_ci():
    """Pins the resolved interpretive gap (U-K1 fix round, 2026-08-25): the must-reject
    resolving power is ``1.96 * chance.std`` (the spread of one trial-level draw), NOT
    ``achieved_resolving_power`` reapplied to the per-trial list (the CI half-width on the
    MEAN across trials, which shrinks with sqrt(trials) and would be far too tight for a
    single-run candidate reading to ever land inside)."""
    chance = ChanceResult(mean=0.001, std=0.0013, trials=1000, per_trial_set_ndcg=[0.001] * 1000)
    rp = chance_level_resolving_power(chance)
    assert rp == pytest.approx(1.96 * 0.0013, abs=1e-12)
    # The rejected reading (CI half-width across trials) would be ~40x tighter at trials=1000
    # and is deliberately NOT what this function returns.
    wrong_reading = 1.96 * 0.0013 / math.sqrt(1000)
    assert rp > wrong_reading * 10


def test_executed_chance_level_is_near_zero_for_sparse_relevance():
    """A large corpus with exactly one relevant document per query should show chance near
    1/N-scale, far below any real system's nDCG@10 -- sanity-checks the Monte Carlo
    machinery against the analytic expectation design Section 4.4 tables."""
    corpus_ids = [f"d{i}" for i in range(2000)]
    qrels = {"q1": {"d0": 1.0}}
    result = executed_chance_level(qrels, ["q1"], corpus_ids, k=10, trials=500, seed=1)
    assert 0.0 <= result.mean < 0.02  # analytic expectation is ~10/2000 * harmonic-ish factor, small
