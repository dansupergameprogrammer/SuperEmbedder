"""Guard-vitality tests for the zero-qrels guard (Coverage Model dimension 11, design
Section 11 item 11): each guard is proven able to fire on the harness's own real code path,
and the guard's own removal must turn a red run green. Run with:

    py -3.13 -m pytest eval/k1/tests/test_guards.py -v
"""
from __future__ import annotations

import pytest

from eval.k1.guards import (
    K1GuardError,
    check_query_convention_recorded,
    check_reused_run_covers_population,
    validate_qrels_join,
)


def _healthy_inputs():
    test_query_ids = ["q1", "q2", "q3"]
    qrels_by_query = {
        "q1": {"d1": 1.0, "d2": 1.0},
        "q2": {"d3": 1.0},
        "q3": {"d4": 2.0, "d5": 0.0},
    }
    corpus_ids = {"d1", "d2", "d3", "d4", "d5", "d6"}
    return test_query_ids, qrels_by_query, corpus_ids


def test_healthy_join_passes():
    test_query_ids, qrels_by_query, corpus_ids = _healthy_inputs()
    report = validate_qrels_join("unit", test_query_ids, qrels_by_query, corpus_ids)
    assert report.test_query_count == 3
    assert report.queries_with_zero_qrels == []
    assert report.total_relevant_in_pool == 4  # d1,d2 (q1), d3 (q2), d4 (q3); d5 score 0 excluded


def test_one_query_with_zero_qrels_rows_aborts():
    """A single test query joining zero qrels rows must abort the whole run -- TE-12
    Section 2.4's failure mode, transplanted to the public-set leg."""
    test_query_ids, qrels_by_query, corpus_ids = _healthy_inputs()
    qrels_by_query = dict(qrels_by_query)
    del qrels_by_query["q2"]  # q2 now has zero qrels rows -- a real join drop
    with pytest.raises(K1GuardError) as exc:
        validate_qrels_join("unit", test_query_ids, qrels_by_query, corpus_ids)
    assert exc.value.code == "K1_QRELS_EMPTY"
    assert "q2" in str(exc.value)


def test_set_level_join_emptied_by_a_real_join_error_aborts():
    """This is the mutation that mirrors an actual query-id/document-id join error: every
    qrels row still exists, but none of the judged document ids appear in the corpus pool
    (e.g. the corpus loader used a different id column, or a revision mismatch shifted
    every id). This is the failure must-reject 2 (design Section 6.4) exercises on real
    candidate vectors; this test exercises it on the guard alone, at zero GPU cost."""
    test_query_ids, qrels_by_query, _real_corpus_ids = _healthy_inputs()
    emptied_corpus_ids = {"zzz1", "zzz2", "zzz3"}  # disjoint from every qrels docid
    with pytest.raises(K1GuardError) as exc:
        validate_qrels_join("unit", test_query_ids, qrels_by_query, emptied_corpus_ids)
    assert exc.value.code == "K1_QRELS_EMPTY"
    assert "join failed" in str(exc.value)


def test_one_query_with_zero_relevant_in_pool_aborts_even_when_others_are_healthy():
    """Probe B (Mendeleev's commissioning spec, Section 4): a query WITH real qrels rows
    whose judged documents do not appear in the corpus pool is refused per-query, even when
    every other query in the same set scores fine -- an aggregate-only check (nonzero total
    relevant-in-pool across the set) would miss this."""
    test_query_ids, qrels_by_query, corpus_ids = _healthy_inputs()
    qrels_by_query = dict(qrels_by_query)
    qrels_by_query["q2"] = {"synthetic-missing-doc": 1.0}  # q2 IS judged, but its only
                                                            # relevant doc is absent from corpus_ids
    with pytest.raises(K1GuardError) as exc:
        validate_qrels_join("unit", test_query_ids, qrels_by_query, corpus_ids)
    assert exc.value.code == "K1_QRELS_EMPTY"
    assert "q2" in str(exc.value)


def test_empty_test_query_list_aborts():
    with pytest.raises(K1GuardError) as exc:
        validate_qrels_join("unit", [], {}, {"d1"})
    assert exc.value.code == "K1_QRELS_EMPTY"


# The other half of Coverage Model dimension 11's requirement -- "the guard's own removal
# must turn a red run green" -- is demonstrated in
# eval/k1/tests/test_rank_score.py::test_guard_removed_turns_the_emptied_join_green,
# because it exercises the scorer this guard sits in front of and lands with that module.


# --------------------------------------------------------------------------------------
# check_query_convention_recorded (design Section 6.2 row 2's refusal condition, TE-49
# amendment, D-SLM5389): "a query embedded with no recorded convention" is refused.
# --------------------------------------------------------------------------------------


def test_query_convention_refuses_when_none():
    with pytest.raises(K1GuardError) as exc:
        check_query_convention_recorded("some-model", None)
    assert exc.value.code == "K1_QUERY_CONVENTION_UNRECORDED"


def test_query_convention_refuses_when_empty_string():
    with pytest.raises(K1GuardError) as exc:
        check_query_convention_recorded("some-model", "")
    assert exc.value.code == "K1_QUERY_CONVENTION_UNRECORDED"


def test_query_convention_passes_when_bare_is_recorded():
    check_query_convention_recorded("some-model", "bare")  # does not raise


def test_query_convention_passes_when_an_instruction_is_recorded():
    check_query_convention_recorded("some-model", "Represent this sentence for searching relevant passages: ")


# --------------------------------------------------------------------------------------
# check_reused_run_covers_population (TE-51 review, H-4, Significant): a candidate-reuse
# ranking (TE-50, embed_runner.ModelSpec.reuse_trec_run_dir) that is missing queries the run
# is scoring must be refused -- ndcg_at_k_own scores a missing query 0.0 rather than excluding
# it, silently depressing the reading instead of failing.
# --------------------------------------------------------------------------------------


def test_reused_run_population_check_passes_when_every_query_is_covered():
    check_reused_run_covers_population("unit", "candidate", ["q1", "q2", "q3"], ["q1", "q2", "q3"])  # does not raise


def test_reused_run_population_check_passes_when_the_run_carries_extra_queries():
    """A reused run covering MORE than the required population is not itself a defect -- only
    a SHORTFALL against the required population is refused."""
    check_reused_run_covers_population("unit", "candidate", ["q1", "q2"], ["q1", "q2", "q3"])  # does not raise


def test_reused_run_population_check_refuses_a_partial_ranking():
    """Executed shape from the review (SciFact truncated to 150 of 300 queries): a run missing
    even one required query id must refuse, not silently score it 0.0."""
    with pytest.raises(K1GuardError) as exc:
        check_reused_run_covers_population("scifact", "qwen3-embedding-0.6b", ["q1", "q2", "q3"], ["q1", "q2"])
    assert exc.value.code == "K1_REUSED_RUN_INCOMPLETE"
    assert "q3" in str(exc.value)


def test_reused_run_population_check_refuses_when_the_run_is_empty():
    with pytest.raises(K1GuardError) as exc:
        check_reused_run_covers_population("unit", "candidate", ["q1"], [])
    assert exc.value.code == "K1_REUSED_RUN_INCOMPLETE"
