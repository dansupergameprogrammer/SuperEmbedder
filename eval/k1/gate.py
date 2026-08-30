"""The K1 gate's F1/F2 floor arithmetic (design `te33-k1-gate-design-2026-08-25.md` Section
4, Wizard project records tree). U-K1 fix round, 2026-08-25, Finding C
(`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md` Section 8): the design states
this arithmetic as text but, before this module, no code computed it -- `rank_score.py` and
`runner.py` report readings only. This module is the verdict stage that reads an executed
run packet (`runner.run_gate`'s return value) and computes the gate's pass/fail decision.

**This module never asserts the instrument's status.** It answers "what would the gate say
about this packet's readings," nothing more -- the verdict it computes carries exactly the
standing of the instrument that produced the readings it was computed from, per the design's
own Section 6.3. That standing is asserted in exactly one place, `eval.k1.COMMISSIONING_NOTICE`,
and every caller of `evaluate_gate` reads it there rather than assuming a status from this
module's silence about it (`StandardsDocument.md` Section 5.4).

**The two floors, quoted from the design:**

- **F1 (Section 4.1), the reference-encoder floor:** "on every set, the candidate's nDCG@10
  must not fall below the reference encoder's nDCG@10 on that set, measured in the same run,
  by more than that set's achieved resolving power. Formally: cand >= ref - RP_achieved."
- **F2 (Section 4.2), the lexical floor:** "on every set, the candidate's nDCG@10 must exceed
  a locally executed BM25 baseline on that set by more than the achieved resolving power."
- **The aggregation rule (Section 4.3):** "The gate passes a candidate if and only if F1 and
  F2 both hold on all four sets. No best-of-N, no averaging, no waiver."
- **The minimum-effect-size rule (Section 4.4):** "The gate acts only on a shortfall larger
  than the set's achieved resolving power. A candidate below a floor by less than RP is
  recorded as 'no shortfall detected at this resolution' and passes." This rule is stated
  once here and applied identically to both floors: a floor is a value (`ref` for F1,
  `bm25` for F2), the shortfall is `floor_value - candidate_value`, and the floor fires
  (fails) only when that shortfall exceeds the achieved resolving power -- never on a
  scale-invariant ratio (`StandardsDocument.md` 5.4's significance-ratio failure mode), and
  the minimum effect size acted on (the achieved RP) is stated in every verdict's own output,
  not left implicit.

**Which resolving power governs.** Every floor evaluation is gated by the *candidate's own*
achieved resolving power on that set (`rank_score.achieved_resolving_power`, computed from
the candidate's own per-query nDCG@10 dispersion in the same run) -- the quantity that states
how precisely this run measured the candidate, which is what a shortfall against either floor
must be judged against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MINIMUM_EFFECT_SIZE_RULE = (
    "The gate acts only on a shortfall larger than the achieved resolving power (RP). A "
    "shortfall <= RP is recorded as 'no shortfall detected at this resolution' and the floor "
    "passes -- design Section 4.4, StandardsDocument.md Section 5.4's minimum-effect-size rule."
)

REFERENCE_SUFFIX = "reference"
BM25_MODEL_NAME = "bm25"
GATE_REQUIRED_SETS = ("scifact", "nfcorpus", "fiqa", "arguana")  # design Section 4.3


@dataclass
class FloorVerdict:
    """One floor's (F1 or F2) evaluation for one candidate on one set."""

    floor: str  # "F1" or "F2"
    floor_label: str  # "reference" or "bm25"
    floor_value: float
    candidate_value: float
    achieved_rp: float
    shortfall: float  # floor_value - candidate_value; <= 0 means candidate met/exceeded the floor
    fires: bool  # True == FAIL: shortfall exceeds achieved_rp
    passed: bool  # not fires
    note: str


def evaluate_floor(
    floor: str, floor_label: str, floor_value: float, candidate_value: float, achieved_rp: float
) -> FloorVerdict:
    """The shared arithmetic behind both F1 and F2 (design Section 4.4's rule, stated once
    and applied identically to both floors -- see module docstring)."""
    shortfall = floor_value - candidate_value
    fires = shortfall > achieved_rp
    if shortfall <= 0:
        note = (
            f"{floor} passes: candidate ({candidate_value:.5f}) meets or exceeds the "
            f"{floor_label} floor ({floor_value:.5f})."
        )
    elif not fires:
        note = (
            f"{floor} passes: shortfall {shortfall:.5f} against the {floor_label} floor "
            f"({floor_value:.5f}) is within the achieved resolving power ({achieved_rp:.5f}) "
            f"-- no shortfall detected at this resolution. {MINIMUM_EFFECT_SIZE_RULE}"
        )
    else:
        note = (
            f"{floor} FAILS: shortfall {shortfall:.5f} against the {floor_label} floor "
            f"({floor_value:.5f}) exceeds the achieved resolving power ({achieved_rp:.5f}). "
            f"{MINIMUM_EFFECT_SIZE_RULE}"
        )
    return FloorVerdict(
        floor=floor,
        floor_label=floor_label,
        floor_value=floor_value,
        candidate_value=candidate_value,
        achieved_rp=achieved_rp,
        shortfall=shortfall,
        fires=fires,
        passed=not fires,
        note=note,
    )


def evaluate_f1(ref_ndcg: float, candidate_ndcg: float, achieved_rp: float) -> FloorVerdict:
    """F1, design Section 4.1: `cand >= ref - RP_achieved`."""
    return evaluate_floor("F1", "reference", ref_ndcg, candidate_ndcg, achieved_rp)


def evaluate_f2(bm25_ndcg: float, candidate_ndcg: float, achieved_rp: float) -> FloorVerdict:
    """F2, design Section 4.2: candidate must exceed the BM25 floor by more than RP_achieved,
    read through the same shortfall-vs-RP arithmetic as F1 (module docstring)."""
    return evaluate_floor("F2", "bm25", bm25_ndcg, candidate_ndcg, achieved_rp)


@dataclass
class SetGateVerdict:
    """F1 and F2, together, for one candidate model on one set."""

    set_name: str
    model_name: str
    f1: FloorVerdict
    f2: FloorVerdict
    passed: bool  # f1.passed and f2.passed


def evaluate_candidate_on_set(set_name: str, model_name: str, candidate_ndcg: float,
                                achieved_rp: float, ref_ndcg: float, bm25_ndcg: float) -> SetGateVerdict:
    f1 = evaluate_f1(ref_ndcg, candidate_ndcg, achieved_rp)
    f2 = evaluate_f2(bm25_ndcg, candidate_ndcg, achieved_rp)
    return SetGateVerdict(set_name=set_name, model_name=model_name, f1=f1, f2=f2, passed=f1.passed and f2.passed)


@dataclass
class GateVerdict:
    """The full gate decision over an executed run packet: every gated (candidate, set) pair,
    the skips (missing reference or bm25 reading), and the overall pass/fail per the
    aggregation rule (design Section 4.3: F1 and F2 both hold, on all four sets, for a given
    candidate model -- no best-of-N, no averaging, no waiver)."""

    per_set: Dict[str, Dict[str, SetGateVerdict]] = field(default_factory=dict)  # set -> model -> verdict
    per_model_passed: Dict[str, bool] = field(default_factory=dict)  # model -> passed all evaluated sets
    skips: List[str] = field(default_factory=list)
    sets_present: List[str] = field(default_factory=list)
    four_set_complete: bool = False
    passed: bool = False
    reason: str = ""


def evaluate_gate(packet: dict) -> GateVerdict:
    """Runs the F1/F2 floor-gate arithmetic (design Section 4) over an executed run packet,
    as produced by `runner.run_gate`. For every model in every set that is neither the
    reference (name ending in "reference") nor "bm25", computes F1 against that set's
    reference reading and F2 against that set's executed BM25 reading -- both read from the
    SAME run/packet the candidate was scored in, never a different run or a stored constant.

    Never invents a reference or bm25 reading: a (set, model) pair missing either is recorded
    in `skips` and excluded from that model's aggregate rather than silently passed or
    failed. The overall `passed` field applies the design's own aggregation rule (Section
    4.3) per model: a model passes the gate only if F1 and F2 both held on every one of the
    four required sets (`GATE_REQUIRED_SETS`) that this packet evaluated for it; a model
    evaluated on fewer than all four sets cannot pass, and `reason` states why.
    """
    per_set: Dict[str, Dict[str, SetGateVerdict]] = {}
    skips: List[str] = []
    model_set_results: Dict[str, Dict[str, SetGateVerdict]] = {}

    sets = packet.get("sets", {})
    for set_name, set_result in sets.items():
        models = set_result.get("models", {})
        ref_model_name = next((n for n in models if n.endswith(REFERENCE_SUFFIX)), None)
        bm25_result = models.get(BM25_MODEL_NAME)
        ref_ndcg: Optional[float] = models[ref_model_name]["ndcg_at_10"] if ref_model_name else None
        bm25_ndcg: Optional[float] = bm25_result["ndcg_at_10"] if bm25_result else None

        per_set[set_name] = {}
        for model_name, model_result in models.items():
            if model_name == ref_model_name or model_name == BM25_MODEL_NAME:
                continue
            if ref_ndcg is None or bm25_ndcg is None:
                missing = "reference" if ref_ndcg is None else "bm25"
                skips.append(f"{set_name}/{model_name}: no {missing} reading in this run")
                continue
            verdict = evaluate_candidate_on_set(
                set_name, model_name, model_result["ndcg_at_10"],
                model_result["achieved_resolving_power"], ref_ndcg, bm25_ndcg,
            )
            per_set[set_name][model_name] = verdict
            model_set_results.setdefault(model_name, {})[set_name] = verdict

    sets_present = sorted(sets.keys())
    four_set_complete = set(GATE_REQUIRED_SETS).issubset(set(sets_present))

    per_model_passed: Dict[str, bool] = {}
    reasons: List[str] = []
    for model_name, by_set in model_set_results.items():
        model_sets_evaluated = set(by_set.keys())
        model_four_set_complete = set(GATE_REQUIRED_SETS).issubset(model_sets_evaluated)
        model_all_pass = all(v.passed for v in by_set.values())
        per_model_passed[model_name] = model_four_set_complete and model_all_pass
        if not model_four_set_complete:
            missing_sets = sorted(set(GATE_REQUIRED_SETS) - model_sets_evaluated)
            reasons.append(f"{model_name}: gated on {sorted(model_sets_evaluated)}, missing {missing_sets}")
        elif not model_all_pass:
            failed_sets = sorted(s for s, v in by_set.items() if not v.passed)
            reasons.append(f"{model_name}: F1/F2 failed on {failed_sets}")

    if not model_set_results:
        reasons.insert(0, "no model/set pair had both a reference and bm25 reading to gate against")
    if skips:
        reasons.append(f"{len(skips)} (set, model) pair(s) skipped for a missing reference/bm25 reading")

    overall_passed = bool(model_set_results) and all(per_model_passed.values())
    reason = "; ".join(reasons) if reasons else "F1 and F2 both pass on all four sets for every gated model"

    return GateVerdict(
        per_set=per_set,
        per_model_passed=per_model_passed,
        skips=skips,
        sets_present=sets_present,
        four_set_complete=four_set_complete,
        passed=overall_passed,
        reason=reason,
    )
