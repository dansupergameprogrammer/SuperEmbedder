"""The K1 gate's F1/F2 floor arithmetic (design `te33-k1-gate-design-2026-08-25.md` Section
4, Wizard project records tree, amended by Section 17, TE-49). U-K1 fix round, 2026-08-25,
Finding C (`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md` Section 8): the
design states this arithmetic as text but, before this module, no code computed it --
`rank_score.py` and `runner.py` report readings only. This module is the verdict stage that
reads an executed run packet (`runner.run_gate`'s return value) and computes the gate's
pass/fail decision.

**This module never asserts the instrument's status.** It answers "what would the gate say
about this packet's readings," nothing more -- the verdict it computes carries exactly the
standing of the instrument that produced the readings it was computed from, per the design's
own Section 6.3. That standing is asserted in exactly one place, `eval.k1.COMMISSIONING_NOTICE`,
and every caller of `evaluate_gate` reads it there rather than assuming a status from this
module's silence about it (`StandardsDocument.md` Section 5.4). One exception, added by the
TE-40 review (Finding F-1): `GateVerdict.uncommissioned_required_sets` names which of
`GATE_REQUIRED_SETS` fall outside `eval.k1.COMMISSIONED_SETS`. This is not a status
assertion -- it is the same kind of fact `required_sets_complete` already states about data
presence, now stated about commissioning presence -- and it takes no position on whether an
uncommissioned set's own reading is good or bad; the notice remains the one place that says
what "uncommissioned" means for the packet as a whole.

**The two floors, quoted from the design as amended by Section 17 (TE-49, D-SLM5387/5388):**

- **F1 (Section 4.1), the reference-encoder floor -- a TRUE FLOOR, shortfall-only:** "on
  every set, the candidate's nDCG@10 must not fall below the reference encoder's nDCG@10 on
  that set, measured in the same run, by more than that set's achieved resolving power.
  Formally: cand >= ref - RP_paired(cand, ref)." The gate acts only on a *shortfall*; a
  candidate not resolvably below the reference passes, whatever margin above it (or below it,
  within RP) it carries -- there is no requirement to resolvably beat the reference.
- **F2 (Section 4.2), the lexical floor -- a BAR TO CLEAR, margin-only, NO null
  disposition:** "on every set, the candidate's nDCG@10 must exceed the locally executed
  BM25 baseline on that set by more than that set's paired resolving power. Formally:
  cand - bm25 > RP_paired(cand, bm25)." Falling short of BM25, tying it, or beating it by
  less than the paired RP all FAIL -- "no shortfall detected against lexical matching" is not
  a disposition F2 supports (design Section 4.4: "there is no null disposition for F2").
  **F1 and F2 are asymmetric by design, not two copies of one rule** -- TE-49's amendment
  (D-SLM5388) resolved a contradiction TE-48's debunk found (A6): this module's own prior
  text routed F2 through the identical shortfall-vs-RP arithmetic as F1, which passed a
  candidate that merely tied or trailed BM25 within RP -- the opposite of what Section 4.2's
  own prose required. `evaluate_f2` below is a distinct function from `evaluate_f1` /
  `evaluate_floor` for exactly this reason; they must never be unified back into one shared
  arithmetic path.
- **The aggregation rule (Section 4.3):** "The gate passes a candidate if and only if F1 and
  F2 both hold on all four sets. No best-of-N, no averaging, no waiver." **Section 16's
  amendment extends "all four sets" to every set the design locks, without reopening the
  conjunction rule itself**: "Section 4.3's aggregation rule is unchanged and applies to
  SCIDOCS identically once it is added to the locked-set roster... F1 ∧ F2, all sets, no
  waiver." `GATE_REQUIRED_SETS` below is therefore read from the roster
  (`eval.k1.set_roster.ALL_LOCKED_SETS`) rather than hardcoded at the four-set count Section
  4.3 was written against, so a future amendment that grows the roster again needs no second
  edit here (TE-40; the roster's own leaf-module location is TE-40 review Finding F-1's
  sibling fix, F-7, below).
- **The minimum-effect-size rule (Section 4.4, amended by Section 17.1, D-SLM5385):** "The
  gate acts only on an effect larger than the achieved resolving power, and the achieved
  resolving power is the PAIRED resolving power -- the dispersion of the per-query
  difference between the two rankings being compared, not either arm's marginal dispersion."
  F1 and F2 each use their OWN paired RP (`rank_score.paired_resolving_power(cand, ref)` and
  `rank_score.paired_resolving_power(cand, bm25)` respectively -- two different numbers per
  set, since the per-query correlation between the candidate and the reference is not the
  correlation between the candidate and BM25). Neither floor acts on a scale-invariant ratio
  (`StandardsDocument.md` 5.4's significance-ratio failure mode); the minimum effect size
  acted on (the achieved, paired RP) is stated in every verdict's own output, not left
  implicit.

**Which resolving power governs.** Every floor evaluation is gated by the PAIRED resolving
power for that specific comparison (`rank_score.paired_resolving_power`, computed from the
per-query DIFFERENCE between the candidate and the floor arm in the same run) -- not the
candidate's own marginal dispersion in isolation, which this module used before the TE-49
amendment and which TE-48's debunk (A3) found 11%-48% too wide on every set of Run 1's
packet, on the paired-vs-marginal axis alone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from eval.k1 import COMMISSIONED_SETS
from eval.k1.set_roster import ALL_LOCKED_SETS

MINIMUM_EFFECT_SIZE_RULE = (
    "The gate acts only on a shortfall larger than the achieved (paired) resolving power "
    "(RP). A shortfall <= RP is recorded as 'no shortfall detected at this resolution' and "
    "the floor passes -- design Section 4.4, StandardsDocument.md Section 5.4's "
    "minimum-effect-size rule. This wording governs F1 (a true floor); F2 uses "
    "MINIMUM_EFFECT_SIZE_RULE_F2 below, which is deliberately the mirror-image statement."
)

MINIMUM_EFFECT_SIZE_RULE_F2 = (
    "F2 acts only on a MARGIN larger than the achieved (paired) resolving power (RP): "
    "cand - bm25 > RP. A margin <= RP -- including a tie or a candidate below BM25 -- FAILS. "
    "There is no null disposition for F2 (design Section 4.4, TE-49 amendment, D-SLM5388): "
    "'no shortfall detected against lexical matching' is not a claim F2 supports."
)

REFERENCE_SUFFIX = "reference"
BM25_MODEL_NAME = "bm25"


def _is_nan(value: object) -> bool:
    """`math.isnan` refuses non-float input (e.g. a value already checked not-None but of
    unexpected type from a hand-built packet); this coerces safely for the None-and-NaN skip
    check in `evaluate_gate`."""
    try:
        return math.isnan(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False

# design Section 4.3, amended by Section 16 (D-SLM4705/D-SLM4686): every set the design locks,
# not a count fixed at four. Read from the roster's own leaf module (`eval.k1.set_roster`,
# TE-40 review Finding F-7 -- moved out of `run_spec.py` so importing this module, whose job
# is reading a JSON packet and computing pass/fail, does not also pull `run_spec.py`'s
# embedding-stack dependencies) rather than retyped here, so the two can never state a
# different set of "required" sets.
GATE_REQUIRED_SETS = ALL_LOCKED_SETS


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
    """F1, design Section 4.1: `cand >= ref - RP_paired(cand, ref)` -- a true floor,
    shortfall-only (module docstring). `achieved_rp` is F1's OWN paired resolving power
    (`rank_score.paired_resolving_power(cand, ref)`), never the candidate's marginal RP nor
    F2's paired RP."""
    return evaluate_floor("F1", "reference", ref_ndcg, candidate_ndcg, achieved_rp)


def evaluate_f2(bm25_ndcg: float, candidate_ndcg: float, achieved_rp: float) -> FloorVerdict:
    """F2, design Section 4.2 (amended by Section 17.2, D-SLM5387/5388): `cand - bm25 >
    RP_paired(cand, bm25)` -- a bar to clear, margin-only, with NO null disposition. This is
    NOT `evaluate_floor`'s shortfall-vs-RP arithmetic (that rule is F1's, and applying it to
    F2 is exactly the defect TE-48's debunk (A6) found: it passed a candidate that merely
    tied or trailed BM25 within RP). `achieved_rp` is F2's OWN paired resolving power
    (`rank_score.paired_resolving_power(cand, bm25)`), distinct from F1's.

    A margin `<= 0` (the candidate does not exceed BM25 at all) and a margin `> 0` but
    `<= achieved_rp` (an unresolved advantage) both FAIL -- the two cases are reported with
    different notes so a reader can tell "behind or tied" from "ahead, but not resolvably,"
    but both are `fires=True`.
    """
    margin = candidate_ndcg - bm25_ndcg
    fires = not (margin > achieved_rp)  # FAIL unless the margin resolvably clears RP
    if margin <= 0:
        note = (
            f"F2 FAILS: candidate ({candidate_ndcg:.5f}) does not exceed the bm25 floor "
            f"({bm25_ndcg:.5f}) -- margin {margin:.5f}. {MINIMUM_EFFECT_SIZE_RULE_F2}"
        )
    elif fires:
        note = (
            f"F2 FAILS: margin {margin:.5f} over the bm25 floor ({bm25_ndcg:.5f}) does not "
            f"exceed the achieved resolving power ({achieved_rp:.5f}) -- no resolved "
            f"advantage over lexical matching. {MINIMUM_EFFECT_SIZE_RULE_F2}"
        )
    else:
        note = (
            f"F2 passes: margin {margin:.5f} over the bm25 floor ({bm25_ndcg:.5f}) exceeds "
            f"the achieved resolving power ({achieved_rp:.5f}) -- resolved advantage over "
            f"lexical matching. {MINIMUM_EFFECT_SIZE_RULE_F2}"
        )
    return FloorVerdict(
        floor="F2",
        floor_label="bm25",
        floor_value=bm25_ndcg,
        candidate_value=candidate_ndcg,
        achieved_rp=achieved_rp,
        shortfall=-margin,  # sign convention matches evaluate_floor's floor_value - candidate_value
        fires=fires,
        passed=not fires,
        note=note,
    )


@dataclass
class SetGateVerdict:
    """F1 and F2, together, for one candidate model on one set."""

    set_name: str
    model_name: str
    f1: FloorVerdict
    f2: FloorVerdict
    passed: bool  # f1.passed and f2.passed


def evaluate_candidate_on_set(set_name: str, model_name: str, candidate_ndcg: float,
                                f1_achieved_rp: float, f2_achieved_rp: float,
                                ref_ndcg: float, bm25_ndcg: float) -> SetGateVerdict:
    """`f1_achieved_rp` and `f2_achieved_rp` are TWO DIFFERENT numbers (design Section 4.4,
    TE-49 amendment): `rank_score.paired_resolving_power(cand, ref)` and
    `rank_score.paired_resolving_power(cand, bm25)` respectively -- never the same value
    passed twice, and never the candidate's marginal resolving power."""
    f1 = evaluate_f1(ref_ndcg, candidate_ndcg, f1_achieved_rp)
    f2 = evaluate_f2(bm25_ndcg, candidate_ndcg, f2_achieved_rp)
    return SetGateVerdict(set_name=set_name, model_name=model_name, f1=f1, f2=f2, passed=f1.passed and f2.passed)


@dataclass
class GateVerdict:
    """The full gate decision over an executed run packet: every gated (candidate, set) pair,
    the skips (missing reference or bm25 reading), and the overall pass/fail per the
    aggregation rule (design Section 4.3, amended by Section 16: F1 and F2 both hold, on
    every required set (`GATE_REQUIRED_SETS`), for a given candidate model -- no best-of-N,
    no averaging, no waiver). `uncommissioned_required_sets` (TE-40 review, F-1) names which
    of those required sets fall outside `eval.k1.COMMISSIONED_SETS` -- independent of
    `passed`, which this module never conditions on commissioning standing."""

    per_set: Dict[str, Dict[str, SetGateVerdict]] = field(default_factory=dict)  # set -> model -> verdict
    per_model_passed: Dict[str, bool] = field(default_factory=dict)  # model -> passed all evaluated sets
    skips: List[str] = field(default_factory=list)
    sets_present: List[str] = field(default_factory=list)
    required_sets_complete: bool = False  # every set in GATE_REQUIRED_SETS is present in this packet
    # TE-40 review, F-1: every set in GATE_REQUIRED_SETS that is outside eval.k1.COMMISSIONED_SETS
    # -- a fact about the instrument's commissioning coverage, independent of whether this
    # packet's own run happened to include that set. Non-empty on every verdict until an
    # independent seat commissions the remaining set(s); see eval.k1.COMMISSIONING_NOTICE.
    uncommissioned_required_sets: List[str] = field(default_factory=list)
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
    failed. **Same for the two paired resolving powers (Section 4.4, TE-49 amendment):** a
    (set, model) pair whose reading carries no `f1_paired_resolving_power` or
    `f2_paired_resolving_power` -- e.g. a packet from before this amendment, or a model that
    shares no test queries with the reference/bm25 arm -- is skipped rather than silently
    graded against the candidate's own marginal resolving power (the pre-amendment behaviour
    TE-48's debunk (A3) found too wide). The overall `passed` field applies the design's own
    aggregation rule (Section 4.3, amended by Section 16) per model: a model passes the gate
    only if F1 and F2 both held on every one of the required sets (`GATE_REQUIRED_SETS`, the
    full locked-set roster -- five sets today, never a count retyped here) that this packet
    evaluated for it; a model evaluated on fewer than every required set cannot pass, and
    `reason` states why.
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
            f1_rp = model_result.get("f1_paired_resolving_power")
            f2_rp = model_result.get("f2_paired_resolving_power")
            if f1_rp is None or f2_rp is None or _is_nan(f1_rp) or _is_nan(f2_rp):
                skips.append(
                    f"{set_name}/{model_name}: no paired resolving power computed for F1/F2 "
                    f"in this run (design Section 4.4, TE-49 amendment)"
                )
                continue
            verdict = evaluate_candidate_on_set(
                set_name, model_name, model_result["ndcg_at_10"],
                f1_rp, f2_rp, ref_ndcg, bm25_ndcg,
            )
            per_set[set_name][model_name] = verdict
            model_set_results.setdefault(model_name, {})[set_name] = verdict

    sets_present = sorted(sets.keys())
    required_sets_complete = set(GATE_REQUIRED_SETS).issubset(set(sets_present))

    per_model_passed: Dict[str, bool] = {}
    reasons: List[str] = []
    for model_name, by_set in model_set_results.items():
        model_sets_evaluated = set(by_set.keys())
        model_required_sets_complete = set(GATE_REQUIRED_SETS).issubset(model_sets_evaluated)
        model_all_pass = all(v.passed for v in by_set.values())
        per_model_passed[model_name] = model_required_sets_complete and model_all_pass
        if not model_required_sets_complete:
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
    reason = "; ".join(reasons) if reasons else "F1 and F2 both pass on every required set for every gated model"

    # TE-40 review, F-1: name which required sets the notice's commissioned cell does not
    # cover, so a reader of the verdict alone -- not only the notice text -- sees that this
    # aggregation includes at least one set whose readings are quarantined pending its own
    # commissioning. Does not change `passed`: this module states facts, it does not decide
    # standing (module docstring, above).
    uncommissioned_required_sets = sorted(set(GATE_REQUIRED_SETS) - set(COMMISSIONED_SETS))
    if uncommissioned_required_sets:
        reason = (
            f"{len(uncommissioned_required_sets)} required set(s) not yet commissioned "
            f"({', '.join(uncommissioned_required_sets)}), quarantined per the commissioning "
            f"disposition rule independent of this verdict's pass/fail; {reason}"
        )

    return GateVerdict(
        per_set=per_set,
        per_model_passed=per_model_passed,
        skips=skips,
        sets_present=sets_present,
        required_sets_complete=required_sets_complete,
        uncommissioned_required_sets=uncommissioned_required_sets,
        passed=overall_passed,
        reason=reason,
    )
