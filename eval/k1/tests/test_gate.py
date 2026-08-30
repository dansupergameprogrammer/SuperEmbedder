"""Tests for the F1/F2 floor-gate arithmetic (`eval/k1/gate.py`, design Section 4). U-K1 fix
round, 2026-08-25, Finding C pin: fire and no-fire on constructed readings on each side of
both components (F1 and F2), plus the aggregation rule (design Section 4.3) and the
minimum-effect-size rule (design Section 4.4)."""
from __future__ import annotations

import pytest

from eval.k1.gate import (
    GATE_REQUIRED_SETS,
    evaluate_f1,
    evaluate_f2,
    evaluate_floor,
    evaluate_gate,
)


# --------------------------------------------------------------------------------------
# evaluate_floor -- the shared shortfall-vs-RP arithmetic
# --------------------------------------------------------------------------------------


def test_floor_passes_when_candidate_meets_the_floor_exactly():
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.50, achieved_rp=0.02)
    assert v.passed and not v.fires
    assert v.shortfall == pytest.approx(0.0)


def test_floor_passes_when_candidate_exceeds_the_floor():
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.60, achieved_rp=0.02)
    assert v.passed and not v.fires
    assert v.shortfall < 0


def test_floor_passes_when_shortfall_is_within_achieved_rp():
    """Design Section 4.4: a shortfall <= RP is 'no shortfall detected at this resolution'
    and PASSES -- the minimum-effect-size rule, not a tolerance loosening."""
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.485, achieved_rp=0.02)
    assert v.shortfall == pytest.approx(0.015)
    assert v.passed and not v.fires
    assert "no shortfall detected" in v.note


def test_floor_fails_when_shortfall_exceeds_achieved_rp():
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.47, achieved_rp=0.02)
    assert v.shortfall == pytest.approx(0.03)
    assert v.fires and not v.passed
    assert "FAILS" in v.note


def test_floor_boundary_at_exactly_rp_does_not_fire():
    """The rule is 'larger than RP', so shortfall == RP exactly does not fire. Uses values
    exactly representable in binary floating point (0.5, 0.25) so the boundary comparison is
    not itself confounded by float subtraction noise."""
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.25, achieved_rp=0.25)
    assert v.shortfall == 0.25
    assert v.passed and not v.fires


def test_floor_boundary_just_above_rp_fires():
    v = evaluate_floor("F1", "reference", floor_value=0.50, candidate_value=0.24, achieved_rp=0.25)
    assert v.fires and not v.passed


# --------------------------------------------------------------------------------------
# F1 -- cand >= ref - RP_achieved (design Section 4.1)
# --------------------------------------------------------------------------------------


def test_f1_fires_when_candidate_resolvably_below_reference():
    v = evaluate_f1(ref_ndcg=0.71273, candidate_ndcg=0.60, achieved_rp=0.02)
    assert v.floor == "F1" and v.fires


def test_f1_does_not_fire_when_candidate_within_rp_of_reference():
    v = evaluate_f1(ref_ndcg=0.71273, candidate_ndcg=0.70, achieved_rp=0.02)
    assert v.floor == "F1" and v.passed


def test_f1_does_not_fire_when_candidate_beats_reference():
    v = evaluate_f1(ref_ndcg=0.71273, candidate_ndcg=0.80, achieved_rp=0.02)
    assert v.floor == "F1" and v.passed


# --------------------------------------------------------------------------------------
# F2 -- candidate must exceed BM25 by more than RP_achieved (design Section 4.2)
# --------------------------------------------------------------------------------------


def test_f2_fires_when_candidate_resolvably_below_bm25():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.40, achieved_rp=0.02)
    assert v.floor == "F2" and v.fires


def test_f2_does_not_fire_when_candidate_within_rp_of_bm25():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.585, achieved_rp=0.02)
    assert v.floor == "F2" and v.passed


def test_f2_does_not_fire_when_candidate_beats_bm25():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.75, achieved_rp=0.02)
    assert v.floor == "F2" and v.passed


# --------------------------------------------------------------------------------------
# evaluate_gate -- the aggregation rule (Section 4.3, amended by Section 16), skip handling
# --------------------------------------------------------------------------------------


def _packet_for_sets(set_names, candidate_ndcg_by_set, ref_ndcg=0.70, bm25_ndcg=0.50, rp=0.02):
    sets = {}
    for name in set_names:
        sets[name] = {
            "models": {
                "bge-small-en-v1.5-reference": {"ndcg_at_10": ref_ndcg},
                "bm25": {"ndcg_at_10": bm25_ndcg},
                "candidate": {"ndcg_at_10": candidate_ndcg_by_set[name], "achieved_resolving_power": rp},
            }
        }
    return {"sets": sets}


def test_gate_passes_a_candidate_that_clears_both_floors_on_every_required_set():
    packet = _packet_for_sets(
        GATE_REQUIRED_SETS,
        {name: 0.72 for name in GATE_REQUIRED_SETS},  # beats ref (0.70) and bm25 (0.50)
    )
    verdict = evaluate_gate(packet)
    assert verdict.passed
    assert verdict.per_model_passed["candidate"] is True
    assert verdict.required_sets_complete


def test_gate_fails_a_candidate_that_fails_f1_on_one_required_set():
    ndcg = {name: 0.72 for name in GATE_REQUIRED_SETS}
    ndcg["nfcorpus"] = 0.30  # resolvably below the 0.70 reference floor
    packet = _packet_for_sets(GATE_REQUIRED_SETS, ndcg)
    verdict = evaluate_gate(packet)
    assert not verdict.passed
    assert verdict.per_model_passed["candidate"] is False
    assert not verdict.per_set["nfcorpus"]["candidate"].f1.passed
    assert verdict.per_set["scifact"]["candidate"].passed  # other sets unaffected


def test_gate_fails_a_candidate_that_fails_f2_on_one_required_set():
    ndcg = {name: 0.72 for name in GATE_REQUIRED_SETS}
    ndcg["fiqa"] = 0.40  # below the 0.50 bm25 floor by more than RP, but well within F1
    packet = _packet_for_sets(GATE_REQUIRED_SETS, ndcg, ref_ndcg=0.10)  # keep F1 slack irrelevant
    verdict = evaluate_gate(packet)
    assert not verdict.per_set["fiqa"]["candidate"].f2.passed
    assert not verdict.passed


def test_gate_never_passes_on_fewer_than_every_required_set_no_best_of_n():
    """Design Section 4.3: 'No best-of-N, no averaging, no waiver.' A run over all but one of
    the required sets, even a run where the candidate clears both floors on every set it WAS
    evaluated on, cannot pass."""
    missing_one = list(GATE_REQUIRED_SETS)[:-1]
    packet = _packet_for_sets(missing_one, {name: 0.90 for name in missing_one})
    verdict = evaluate_gate(packet)
    assert not verdict.passed
    assert not verdict.required_sets_complete
    assert verdict.per_model_passed["candidate"] is False


def test_gate_requires_scidocs_specifically_not_only_the_original_four():
    """TE-40 (D-SLM5302's fix): GATE_REQUIRED_SETS is the design's Section 16 roster (five
    sets, SCIDOCS included), not the four sets Section 4.3 was originally written against.
    A candidate that clears both floors on the original four but FAILS F1 on SCIDOCS must not
    pass the gate -- before this fix, GATE_REQUIRED_SETS omitted 'scidocs' entirely, so
    `required_sets_complete` (then named `four_set_complete`) was already True without it and
    the aggregate `passed` never looked at SCIDOCS's own verdict at all."""
    assert "scidocs" in GATE_REQUIRED_SETS, "the fix this test pins has regressed"
    original_four = [s for s in GATE_REQUIRED_SETS if s != "scidocs"]
    ndcg = {name: 0.72 for name in original_four}  # clears both floors on all four
    ndcg["scidocs"] = 0.10  # resolvably below the 0.70 reference floor -- F1 fails
    packet = _packet_for_sets(GATE_REQUIRED_SETS, ndcg)
    verdict = evaluate_gate(packet)
    assert verdict.required_sets_complete  # all five sets ARE present in this packet
    assert not verdict.per_set["scidocs"]["candidate"].f1.passed  # SCIDOCS itself fails F1
    for name in original_four:
        assert verdict.per_set[name]["candidate"].passed  # every other set is clean
    assert verdict.per_model_passed["candidate"] is False  # SCIDOCS's failure must veto
    assert not verdict.passed


def test_gate_skips_a_set_missing_a_reference_reading_rather_than_inventing_one():
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.90 for name in GATE_REQUIRED_SETS})
    del packet["sets"]["scifact"]["models"]["bge-small-en-v1.5-reference"]
    verdict = evaluate_gate(packet)
    assert any("scifact/candidate" in s and "reference" in s for s in verdict.skips)
    assert "scifact" not in verdict.per_set.get("scifact", {}) or not verdict.per_set["scifact"]


def test_gate_skips_a_set_missing_a_bm25_reading_rather_than_inventing_one():
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.90 for name in GATE_REQUIRED_SETS})
    del packet["sets"]["fiqa"]["models"]["bm25"]
    verdict = evaluate_gate(packet)
    assert any("fiqa/candidate" in s and "bm25" in s for s in verdict.skips)


def test_gate_evaluates_multiple_candidate_models_independently():
    sets = {}
    for name in GATE_REQUIRED_SETS:
        sets[name] = {
            "models": {
                "bge-small-en-v1.5-reference": {"ndcg_at_10": 0.70},
                "bm25": {"ndcg_at_10": 0.50},
                "good-candidate": {"ndcg_at_10": 0.72, "achieved_resolving_power": 0.02},
                "bad-candidate": {"ndcg_at_10": 0.10, "achieved_resolving_power": 0.02},
            }
        }
    verdict = evaluate_gate({"sets": sets})
    assert verdict.per_model_passed["good-candidate"] is True
    assert verdict.per_model_passed["bad-candidate"] is False
    assert not verdict.passed  # aggregate over all gated models


def test_gate_note_states_the_minimum_effect_size_rule():
    """Finding C's brief requires the minimum-effect-size rule to be stated IN the output,
    not just applied silently."""
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.685 for name in GATE_REQUIRED_SETS})
    verdict = evaluate_gate(packet)
    note = verdict.per_set["scifact"]["candidate"].f1.note
    assert "resolving power" in note.lower()
