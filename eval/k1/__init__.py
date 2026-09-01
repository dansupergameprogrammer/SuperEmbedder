"""U-K1 -- the K1 retrieval-quality gate's instrument.

Built to `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (design of record, the Wizard
project's records tree). This package is the instrument only: it loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet.

COMMISSIONING NOTICE (StandardsDocument.md 5.4, "An instrument is commissioned before its
verdicts are load-bearing -- and never by its own maker"): the commissioning constructions
(the must-accept and the two must-reject constructions named in the design's Section 6.4)
are authored by a seat independent of this instrument's builder, not by this package.
`COMMISSIONED_SETS` below names every set an independent seat has run all three against and
filed a COMMISSIONED verdict for; `COMMISSIONING_DECISIONS` cites the exact decision ID per
set. Two passes commissioned the five sets currently in `COMMISSIONED_SETS`:

- **SciFact, NFCorpus, FiQA-2018, ArguAna** -- commissioned together at instrument commit
  `3426bee` (D-SLM4707, 2026-08-25,
  `Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md`): all three constructions
  fire correctly and the zero-qrels guard's vitality is proven.
- **SCIDOCS** -- commissioned separately, in two rounds. The first attempt (TE-41, D-SLM5338,
  2026-08-30) found must-accept and must-reject 1 fired but must-reject 2 (the qrels-
  permutation join attack) did not, on SCIDOCS's own topically clustered query list, and
  filed **NOT COMMISSIONED**. An independent seat then built and executed a content-distance-
  aware derangement construction for SCIDOCS specifically -- replacing the original fixed
  positional shift, not loosening its tolerance -- and re-verdicted **COMMISSIONED** (TE-46,
  D-SLM5363, 2026-08-30,
  `Claude/Mendeleev/te46-scidocs-mustreject2-remedy-2026-08-30.md`).

Readings this instrument produces on any set in `COMMISSIONED_SETS`, from the commit that
set's own verdict was filed at forward, are load-bearing.

**A Note that survives alongside SCIDOCS's COMMISSIONED status, per the filed verdict itself
(D-SLM5363, carried forward from D-SLM5338): SCIDOCS's must-reject-1 construction fires by a
narrow margin.** Its reading exceeds its own executed resolving power by roughly 3e-05 --
independently measured twice (TE-41, TE-46) and both times a genuine boundary case, not a
mechanically-failed one: corroborated across three seeds' percentile placement within the
chance distribution, non-replicating at two alternate embedding dimensions, and independently
backed by an F2 (local BM25 floor) rejection of the same construction at roughly 11x its own
resolving power regardless of how the boundary itself resolves. A reader who sees only
"SCIDOCS: COMMISSIONED" does not learn this on their own -- it is stated here so they do.

**A construction that fires does not retroactively validate a different, unexecuted
configuration** (commissioning spec disposition rule,
`Claude/Mendeleev/u-k1-commissioning-2026-08-25.md` Section 5, first sentence). A locked set
outside `COMMISSIONED_SETS` -- present in `eval.k1.set_roster.ALL_LOCKED_SETS` but never
independently commissioned in its own right -- carries no commissioning of its own: its
readings stay quarantined (recorded, never acted on, never headlined, not read into any
gate verdict as load-bearing) until an independent seat runs the must-accept and both
must-reject constructions against it and files the executed verdict as a follow-on
decision-log entry citing the commissioning spec. **This is distinct from, and additional
to, the design's own component re-commissioning rule** (disposition rule's second sentence):
any subsequent change to the loader, ranker, scorer, or guard requires the affected
constructions to be re-fired, on every set they touch, before a new reading from the changed
code is trusted -- a rule about the code changing, not about a set being added.

This is the ONE place that status is asserted; every other reference in this package points
back here rather than restating it, so a future status change is one edit, not a search.
Every entry point in this package prints this notice before emitting a result.
`eval/k1/tests/test_commissioned_sets_pin.py` pins `COMMISSIONED_SETS` against
`COMMISSIONING_DECISIONS` and, where reachable, against the filed decision-log entries
themselves, so this constant cannot silently drift from the record again.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# The set names an independent seat has fired all three commissioning constructions against
# and filed a COMMISSIONED verdict for: SciFact, NFCorpus, FiQA-2018, ArguAna together
# (D-SLM4707, `Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md` Section 7) and
# SCIDOCS separately, on its own remedy construction, after a first attempt returned NOT
# COMMISSIONED (D-SLM5338). The remedy re-verdicted COMMISSIONED, superseding D-SLM5338
# (D-SLM5363, `Claude/Mendeleev/te46-scidocs-mustreject2-remedy-2026-08-30.md` Section 8). A
# locked set not in this tuple has never had its own must-accept/must-reject constructions
# fired -- see the disposition rule quoted in the module docstring above. Grows only when a
# third context executes the constructions against a newly-added set and logs the verdict as
# a decision-log entry citing the commissioning spec
# (`Claude/Mendeleev/u-k1-commissioning-2026-08-25.md` Section 5) -- never by editing this
# tuple to match the roster without that execution having happened.
# `COMMISSIONING_DECISIONS` below cites the decision ID per set; the two are pinned together
# by `eval/k1/tests/test_commissioned_sets_pin.py`.
COMMISSIONED_SETS = ("scifact", "nfcorpus", "fiqa", "arguana", "scidocs")

# Per-set citation into Claude/Decisions/DecisionLog.md (Wizard project records tree): the
# decision ID whose own entry filed that set's executed COMMISSIONED verdict.
# eval/k1/tests/test_commissioned_sets_pin.py pins COMMISSIONED_SETS against this table (must
# name exactly the same sets) and, when the sibling records repository is reachable, against
# the cited entries' own text -- so neither can drift from the other, or from the filed
# record, without a test failing.
COMMISSIONING_DECISIONS = {
    "scifact": "D-SLM4707",
    "nfcorpus": "D-SLM4707",
    "fiqa": "D-SLM4707",
    "arguana": "D-SLM4707",
    "scidocs": "D-SLM5363",
}

# Display names for the notice's own prose -- TE-51 review, H-11: keyed by the same set names
# `COMMISSIONED_SETS` and `COMMISSIONING_DECISIONS` use, so a name list built from the live
# cell (via `commissioned_names_clause` below) can never spell a set differently than the
# constant it was generated from.
SET_DISPLAY_NAMES = {
    "scifact": "SciFact",
    "nfcorpus": "NFCorpus",
    "fiqa": "FiQA-2018",
    "arguana": "ArguAna",
    "scidocs": "SCIDOCS",
}


def commissioned_names_clause(commissioned_sets) -> str:
    """Builds a comma-joined display-name clause FROM ``commissioned_sets`` (normally
    ``COMMISSIONED_SETS``, or a subset of it grouped by decision id) rather than a hand-typed
    prose list -- TE-51 review, H-11 (Minor): the notice's own guarding test
    (`eval/k1/tests/test_commissioning_notice.py`) asserted five hardcoded display names, which
    ``COMMISSIONED_SETS == ALL_LOCKED_SETS`` (post-TE-47) satisfies exactly as well as it would
    have satisfied a genuinely over-broad claim -- the test could no longer fail on the property
    it was written to catch. Generating the clause from its argument, rather than typing it by
    hand, makes a set's presence in the clause and its presence in ``commissioned_sets``
    mechanically the same fact: remove a set from the cell and the display name this function
    would produce is mechanically absent too, not merely absent from a prose list someone
    remembered to edit."""
    return ", ".join(SET_DISPLAY_NAMES[name] for name in commissioned_sets)


# Additional narrative context for a decision id's own commissioning clause in the notice --
# separate from COMMISSIONING_DECISIONS (which CITES the decision) so that a decision id can
# be added there and immediately get its own clause in the notice (TE-53 review, J-7) even
# before anyone has written the narrative aside for it. A decision id absent from this table
# still gets a clause -- generic rather than annotated -- never silently omitted.
COMMISSIONING_NARRATIVE = {
    "D-SLM4707": (
        "2026-08-25, instrument commit 3426bee; the zero-qrels guard's vitality proven on "
        "this group"
    ),
    "D-SLM5363": (
        "2026-08-30, on a content-distance-aware remedy construction for must-reject 2, "
        "after a first attempt -- D-SLM5338 -- returned NOT COMMISSIONED on the original "
        "construction"
    ),
}


def _commissioning_clauses_by_decision(commissioned_sets) -> str:
    """Builds one load-bearing clause per decision id actually present in
    `COMMISSIONING_DECISIONS`, grouping `commissioned_sets` by the decision that commissioned
    each -- TE-53 review, J-7 (Observation): the notice previously filtered on two literal
    decision-id strings, so a set commissioned under a THIRD id (how every future
    commissioning arrives, since each is filed as its own decision-log entry) matched neither
    filter and the notice built cleanly while silently omitting it, even though the notice's
    first sentence still asserted load-bearing standing on all of `COMMISSIONED_SETS`.
    Grouping by the live mapping instead makes a set's presence in some clause and its
    presence in `COMMISSIONED_SETS` mechanically the same fact -- the same property
    `commissioned_names_clause` already gives the name list within one clause."""
    groups: Dict[str, List[str]] = {}
    for s in commissioned_sets:
        groups.setdefault(COMMISSIONING_DECISIONS[s], []).append(s)
    clauses = []
    for decision_id in sorted(groups):
        names = commissioned_names_clause(groups[decision_id])
        narrative = COMMISSIONING_NARRATIVE.get(decision_id)
        if narrative:
            clauses.append(f"{names} ({decision_id}, {narrative})")
        else:
            clauses.append(f"{names} ({decision_id} -- see eval.k1.COMMISSIONING_DECISIONS)")
    return " and ".join(clauses)


# TE-53 review, J-1 (Significant) / J-2 (Significant): RECOMMISSIONING_OUTSTANDING and
# RECOMMISSIONING_NOTE used to be a hand-set boolean and a hand-typed string -- both asserted
# a fact (which commissioned-component modules changed since which set's own commissioning
# baseline) that this repository's own git history already states as data. J-1 found the
# hand-typed note incomplete about the very commit that authored it; J-2 found the root: a
# hand-set flag cannot re-arm once correctly cleared, so the NEXT component change after a
# re-commissioning would ship with the flag silently reading False again. Both close the same
# way `uncommissioned_required_sets` (TE-40 review, F-1) already closed the sibling gap for an
# uncommissioned SET: compute the fact from what actually changed, rather than typing a claim
# about it.
#
# COMMISSIONED_COMPONENT_FILES names the concrete files the disposition rule's component
# sentence ("the loader, ranker, scorer, or guard") means in this instrument.
# COMMISSIONED_AT_COMMIT cites, per decision id, the instrument commit that decision's own
# COMMISSIONED verdict was executed against (module docstring above: "instrument commit
# 3426bee" for D-SLM4707; D-SLM5363's own decision-log entry cites
# "fix/te40-k1-stale-truth@263a750"). Both grow only alongside COMMISSIONING_DECISIONS, under
# the same discipline: a new file or a new baseline commit is added when a filed verdict's own
# text names it, never edited to make a real diff disappear.
COMMISSIONED_COMPONENT_FILES: Tuple[str, ...] = (
    "eval/k1/bm25_baseline.py",
    "eval/k1/embed_runner.py",
    "eval/k1/gate.py",
    "eval/k1/guards.py",
    "eval/k1/rank_score.py",
    "eval/k1/runner.py",
    "eval/k1/sets_lock.py",
)

COMMISSIONED_AT_COMMIT: Dict[str, str] = {
    "D-SLM4707": "3426bee",
    "D-SLM5363": "263a750",
}

_K1_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _K1_PACKAGE_DIR.parents[1]  # eval/k1 -> eval -> repository root


class _RecommissioningCheckUnavailable(RuntimeError):
    """Raised internally when the git query a component's re-commissioning gap depends on
    cannot be answered -- no `git` binary, this directory not a git checkout, or a cited
    baseline commit unreachable (e.g. a shallow clone). Never escapes
    `_derive_recommissioning_gap`: caught there and folded into an outstanding result, because
    a check that could not run is not evidence of a clear one."""


def _component_files_changed_since(commit: str, to_ref: str = "HEAD") -> List[str]:
    """Runs `git diff --name-only <commit>..<to_ref>`, scoped to
    `COMMISSIONED_COMPONENT_FILES`, from the repository this package is checked out in.
    `to_ref` defaults to `HEAD` for real use; a test passes a fixed historical commit so it can
    reproduce a past finding without depending on where this branch's HEAD happens to be today.
    Raises `_RecommissioningCheckUnavailable` -- never a bare subprocess exception -- on any
    failure, so the caller fails toward "outstanding" rather than toward a silent, unverified
    "clear"."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{commit}..{to_ref}", "--", *COMMISSIONED_COMPONENT_FILES],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RecommissioningCheckUnavailable(f"git diff could not run: {exc}") from exc
    if result.returncode != 0:
        raise _RecommissioningCheckUnavailable(
            f"git diff --name-only {commit}..{to_ref} exited {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _derive_recommissioning_gap() -> Tuple[bool, str]:
    """Computes the component re-commissioning gap from git history rather than from a
    hand-typed claim (TE-53 review, J-1/J-2).

    For every decision id currently backing a commissioned set (the values of
    `COMMISSIONING_DECISIONS`), diffs `COMMISSIONED_COMPONENT_FILES` from that decision's own
    `COMMISSIONED_AT_COMMIT` baseline to `HEAD` -- the disposition rule's component sentence,
    executed rather than paraphrased. A decision id with no changed files since its own
    baseline contributes nothing to the result; grouped by decision id, the same shape
    `commissioned_names_clause` already groups the notice's set-name text by, so a set
    commissioned under a new decision id (J-7's own class) is covered by construction, not by
    a list someone remembers to extend.

    Fails toward outstanding rather than toward silence: a decision id with no
    `COMMISSIONED_AT_COMMIT` entry, or a git query that cannot be answered at all (no git
    binary, this directory not a checkout, or a cited commit unreachable), is folded into the
    result as outstanding, with a note naming the check that could not run -- never as a quiet
    `False` that nothing actually verified.
    """
    active_decision_ids = sorted(set(COMMISSIONING_DECISIONS.values()))
    problems: List[str] = []
    changes_by_decision: Dict[str, List[str]] = {}
    for decision_id in active_decision_ids:
        baseline = COMMISSIONED_AT_COMMIT.get(decision_id)
        if baseline is None:
            problems.append(
                f"{decision_id} has no COMMISSIONED_AT_COMMIT baseline -- its component "
                f"re-commissioning gap cannot be computed and is treated as outstanding"
            )
            continue
        try:
            changed = _component_files_changed_since(baseline)
        except _RecommissioningCheckUnavailable as exc:
            problems.append(f"{decision_id} (baseline {baseline}): {exc}")
            continue
        if changed:
            changes_by_decision[decision_id] = changed

    if not problems and not changes_by_decision:
        return False, ""

    parts = []
    for decision_id in sorted(changes_by_decision):
        changed = changes_by_decision[decision_id]
        baseline = COMMISSIONED_AT_COMMIT[decision_id]
        parts.append(
            f"since {decision_id}'s own commissioning baseline ({baseline}), "
            f"{', '.join(changed)} changed"
        )
    for problem in problems:
        parts.append(f"UNVERIFIED -- {problem}")

    note = (
        "Component re-commissioning gap, computed from git history rather than asserted: "
        + "; ".join(parts) + ". D-SLM5396/D-SLM5397 (Wizard project records tree) record and "
        "defer the gap this replaces the hand-typed claim about. No reading this instrument "
        "produces from any listed change forward has been re-commissioned against the "
        "changed code. Flip to False only by an independent seat re-firing the affected "
        "constructions and filing a fresh decision-log entry that updates "
        "COMMISSIONED_AT_COMMIT to the new baseline commit -- never by editing this note or "
        "this function."
    )
    return True, note


RECOMMISSIONING_OUTSTANDING, RECOMMISSIONING_NOTE = _derive_recommissioning_gap()


def _recommissioning_clause(outstanding: bool, note: str) -> str:
    """The notice's live-fact half (TE-51 H-2): non-empty only while re-commissioning is
    actually outstanding, so the sentence disappears the moment ``RECOMMISSIONING_OUTSTANDING``
    is correctly flipped to ``False`` -- no second edit to this string required, the same
    property ``commissioned_names_clause`` gives the set-name list above."""
    if not outstanding:
        return ""
    return f" RE-COMMISSIONING CURRENTLY OUTSTANDING (TE-51 H-2): {note}"


COMMISSIONING_NOTICE = (
    "U-K1 INSTRUMENT -- COMMISSIONED ON eval.k1.COMMISSIONED_SETS ONLY. All three "
    "commissioning constructions (must-accept, must-reject 1, must-reject 2) fire correctly "
    f"and readings are load-bearing on: "
    f"{_commissioning_clauses_by_decision(COMMISSIONED_SETS)}. "
    "See eval.k1.COMMISSIONING_DECISIONS for the "
    "decision ID governing each set. NOTE ON SCIDOCS: its must-reject-1 construction fires by "
    "a narrow margin -- exceeds its own resolving power by roughly 3e-05, a genuine boundary "
    "case independently measured twice, corroborated across three seeds, non-replicating at "
    "two alternate dimensions, and independently backed by an F2 floor rejection at roughly "
    "11x its own resolving power regardless. A construction that fires does not "
    "retroactively validate a different, unexecuted configuration (commissioning spec "
    "Section 5): any other locked set -- present in eval.k1.set_roster.ALL_LOCKED_SETS but "
    "absent from eval.k1.COMMISSIONED_SETS -- has never had its own must-accept/must-reject "
    "constructions fired, and its readings stay quarantined (recorded, never acted on, never "
    "headlined, not read into any gate verdict as load-bearing) until an independent seat "
    "runs them and files the executed verdict as a decision-log entry citing the "
    "commissioning spec. Readings are ALSO subject to the design's own component "
    "re-commissioning rule, which is a separate condition: any subsequent change to the "
    "loader, ranker, scorer, or guard requires the constructions it touches to be re-fired, "
    "on every set they touch, before a new reading from the changed code is trusted "
    "(Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md, "
    "Claude/Mendeleev/te46-scidocs-mustreject2-remedy-2026-08-30.md, and "
    "Claude/Mendeleev/u-k1-commissioning-2026-08-25.md Section 5, Wizard project records "
    "tree)."
) + _recommissioning_clause(RECOMMISSIONING_OUTSTANDING, RECOMMISSIONING_NOTE)
