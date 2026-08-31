"""Tests for the F1/F2 floor-gate arithmetic (`eval/k1/gate.py`, design Section 4, amended by
Section 17, TE-49). U-K1 fix round, 2026-08-25, Finding C pin: fire and no-fire on
constructed readings on each side of both components (F1 and F2), plus the aggregation rule
(design Section 4.3) and the minimum-effect-size rule (design Section 4.4). TE-50 pass,
2026-08-30: F1 stays shortfall-only over its own PAIRED resolving power; F2 is rewritten as a
margin-only rule with no null disposition (D-SLM5387/5388), and the packet fixture below
carries `f1_paired_resolving_power`/`f2_paired_resolving_power` rather than a single shared
`achieved_resolving_power`, per D-SLM5385."""
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
# F2 -- candidate must exceed BM25 by MORE than RP_paired, a bar to clear, no null
# disposition (design Section 4.2, amended by Section 17.2, D-SLM5387/5388).
# --------------------------------------------------------------------------------------


def test_f2_fires_when_candidate_resolvably_below_bm25():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.40, achieved_rp=0.02)
    assert v.floor == "F2" and v.fires


def test_f2_fires_when_candidate_within_rp_below_bm25():
    """The asymmetric rule's core pin (TE-48 debunk A6, D-SLM5388): under the OLD
    shortfall-vs-RP arithmetic (`evaluate_floor`), a candidate trailing BM25 by less than RP
    would PASS. F2 has no such null disposition -- it FAILS."""
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.585, achieved_rp=0.02)
    assert v.floor == "F2" and v.fires and not v.passed


def test_f2_fires_on_an_exact_tie():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.60, achieved_rp=0.02)
    assert v.fires and not v.passed


def test_f2_fires_when_margin_exists_but_does_not_exceed_rp():
    """A positive margin that does not resolvably clear RP is still a FAIL -- distinct from
    F1, where a shortfall within RP is a PASS (null). Uses values exactly representable in
    binary floating point (0.5, 0.75, 0.25) so the margin == RP boundary is not itself
    confounded by float subtraction noise (mirrors `test_floor_boundary_at_exactly_rp_does_not_fire`)."""
    v = evaluate_f2(bm25_ndcg=0.50, candidate_ndcg=0.75, achieved_rp=0.25)
    assert v.shortfall == -0.25
    assert v.fires and not v.passed


def test_f2_passes_only_when_margin_strictly_exceeds_rp():
    v = evaluate_f2(bm25_ndcg=0.50, candidate_ndcg=0.76, achieved_rp=0.25)
    assert v.passed and not v.fires


def test_f2_does_not_fire_when_candidate_beats_bm25_by_more_than_rp():
    v = evaluate_f2(bm25_ndcg=0.60, candidate_ndcg=0.75, achieved_rp=0.02)
    assert v.floor == "F2" and v.passed


def test_f2_is_not_evaluate_floors_shortfall_rule():
    """Pins the two functions as genuinely distinct arithmetic (not merely distinct call
    sites over one shared rule): the same inputs given to `evaluate_floor` (F1's shortfall-
    only rule) and to `evaluate_f2` (the margin-only rule) disagree on this construction,
    exactly TE-48's debunk A6 table's second row (cand=0.480, bm25=0.500, RP=0.04): the
    shortfall reading passes, the design's literal F2 fails."""
    shortfall_reading = evaluate_floor("F2", "bm25", floor_value=0.500, candidate_value=0.480, achieved_rp=0.04)
    literal_f2 = evaluate_f2(bm25_ndcg=0.500, candidate_ndcg=0.480, achieved_rp=0.04)
    assert shortfall_reading.passed is True
    assert literal_f2.passed is False


# --------------------------------------------------------------------------------------
# evaluate_gate -- the aggregation rule (Section 4.3, amended by Section 16), skip handling
# --------------------------------------------------------------------------------------


def _packet_for_sets(set_names, candidate_ndcg_by_set, ref_ndcg=0.70, bm25_ndcg=0.50, rp=0.02):
    """`rp` is used as BOTH `f1_paired_resolving_power` and `f2_paired_resolving_power` in
    these fixtures -- the two are independent numbers in a real packet (design Section 4.4),
    but nothing below this helper's own tests exercises their difference, so one shared
    value keeps the fixture simple; `test_gate_uses_the_f1_and_f2_specific_paired_rp`, below,
    is the pin that the two are read independently rather than one shared field."""
    sets = {}
    for name in set_names:
        sets[name] = {
            "models": {
                "bge-small-en-v1.5-reference": {"ndcg_at_10": ref_ndcg},
                "bm25": {"ndcg_at_10": bm25_ndcg},
                "candidate": {
                    "ndcg_at_10": candidate_ndcg_by_set[name],
                    "achieved_resolving_power": rp,  # marginal, diagnostic only -- unused by the gate
                    "f1_paired_resolving_power": rp,
                    "f2_paired_resolving_power": rp,
                },
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
                "good-candidate": {
                    "ndcg_at_10": 0.72, "achieved_resolving_power": 0.02,
                    "f1_paired_resolving_power": 0.02, "f2_paired_resolving_power": 0.02,
                },
                "bad-candidate": {
                    "ndcg_at_10": 0.10, "achieved_resolving_power": 0.02,
                    "f1_paired_resolving_power": 0.02, "f2_paired_resolving_power": 0.02,
                },
            }
        }
    verdict = evaluate_gate({"sets": sets})
    assert verdict.per_model_passed["good-candidate"] is True
    assert verdict.per_model_passed["bad-candidate"] is False
    assert not verdict.passed  # aggregate over all gated models


def test_gate_uses_the_f1_and_f2_specific_paired_rp_independently():
    """F1 and F2 read DIFFERENT fields (design Section 4.4, TE-49 amendment, D-SLM5385): a
    packet where F1's paired RP is wide enough to null a shortfall but F2's paired RP is too
    tight to absorb an equal-sized margin shortfall must fail F2 while passing F1 -- proving
    the gate reads `f1_paired_resolving_power` and `f2_paired_resolving_power` independently
    rather than one shared field applied to both."""
    sets = {
        "only": {
            "models": {
                "bge-small-en-v1.5-reference": {"ndcg_at_10": 0.70},
                "bm25": {"ndcg_at_10": 0.50},
                "candidate": {
                    "ndcg_at_10": 0.685,  # 0.015 below ref, 0.185 above bm25
                    "f1_paired_resolving_power": 0.02,   # 0.015 shortfall <= 0.02 -> F1 passes (null)
                    "f2_paired_resolving_power": 0.20,   # 0.185 margin <= 0.20 -> F2 FAILS (no null)
                },
            }
        }
    }
    verdict = evaluate_gate({"sets": sets})
    assert verdict.per_set["only"]["candidate"].f1.passed is True
    assert verdict.per_set["only"]["candidate"].f2.passed is False


def test_gate_skips_a_pair_missing_a_paired_resolving_power():
    """A (set, model) reading with no `f1_paired_resolving_power` / `f2_paired_resolving_power`
    -- e.g. a pre-TE-49 packet -- is skipped rather than silently graded, matching the
    existing skip-on-missing-reference/bm25 convention."""
    sets = {
        "scifact": {
            "models": {
                "bge-small-en-v1.5-reference": {"ndcg_at_10": 0.70},
                "bm25": {"ndcg_at_10": 0.50},
                "candidate": {"ndcg_at_10": 0.90},  # no paired RP fields at all
            }
        }
    }
    verdict = evaluate_gate({"sets": sets})
    assert any("no paired resolving power" in s for s in verdict.skips)
    assert verdict.per_set["scifact"] == {}


def test_gate_note_states_the_minimum_effect_size_rule():
    """Finding C's brief requires the minimum-effect-size rule to be stated IN the output,
    not just applied silently."""
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.685 for name in GATE_REQUIRED_SETS})
    verdict = evaluate_gate(packet)
    note = verdict.per_set["scifact"]["candidate"].f1.note
    assert "resolving power" in note.lower()


# --------------------------------------------------------------------------------------
# uncommissioned_required_sets (TE-40 review, F-1: SCIDOCS became gate-deciding while
# uncommissioned, and nothing in the verdict said so).
# --------------------------------------------------------------------------------------


def test_gate_verdict_names_an_uncommissioned_required_set(monkeypatch):
    """GATE_REQUIRED_SETS is the design's full locked-set roster (Section 16). A passing,
    fully-evaluated verdict must still name any gap against eval.k1.COMMISSIONED_SETS -- a
    reader of the verdict alone, not only the notice text, must be able to see that this
    aggregation includes at least one set whose readings are quarantined pending its own
    commissioning.

    TE-41/TE-46/TE-47: SCIDOCS was that real-world gap (D-SLM5338, NOT COMMISSIONED) until
    an independent seat built and executed a remedy construction and re-verdicted COMMISSIONED
    (D-SLM5363), which this repository's own eval.k1.COMMISSIONED_SETS now reflects -- so this
    pin no longer has a real-world uncommissioned required set to point at. It demonstrates the
    same mechanism generically instead, via monkeypatch, exactly as the sibling test below
    demonstrates the gap closing: this test demonstrates the gap opening."""
    import eval.k1.gate as gate_mod

    monkeypatch.setattr(
        gate_mod, "COMMISSIONED_SETS", tuple(s for s in GATE_REQUIRED_SETS if s != "scidocs")
    )
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.90 for name in GATE_REQUIRED_SETS})
    verdict = evaluate_gate(packet)
    assert verdict.passed
    assert verdict.uncommissioned_required_sets == ["scidocs"]
    assert "not yet commissioned" in verdict.reason
    assert "scidocs" in verdict.reason


def test_gate_verdict_uncommissioned_required_sets_is_empty_once_a_set_is_added_to_the_cell(monkeypatch):
    """Demonstrates the field tracks eval.k1.COMMISSIONED_SETS rather than being pinned to
    'scidocs' by name: once a set is added to the commissioned cell, the gap it named closes
    without any edit to gate.py."""
    import eval.k1.gate as gate_mod

    monkeypatch.setattr(gate_mod, "COMMISSIONED_SETS", tuple(GATE_REQUIRED_SETS))
    packet = _packet_for_sets(GATE_REQUIRED_SETS, {name: 0.90 for name in GATE_REQUIRED_SETS})
    verdict = evaluate_gate(packet)
    assert verdict.uncommissioned_required_sets == []
    assert "not yet commissioned" not in verdict.reason
