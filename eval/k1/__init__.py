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


# TE-51 review, H-2 (Critical): the commissioning constructions ARE independent of the
# instrument's build (module docstring above) -- but the constructions fired against CODE, and
# `b16ac70` (TE-50) changed four commissioned components -- `bm25_baseline._tokenize` (the BM25
# analyzer), `embed_runner` (the reference's query vectors), `rank_score` (the paired resolving
# power dispersion) and `gate.evaluate_f2` (the verdict arithmetic) -- after EVERY set in
# `COMMISSIONED_SETS` had its own verdict filed. D-SLM5396 records the gap; D-SLM5397 defers it
# explicitly "before K1-Run-2's verdict is read as load-bearing." No reading this instrument has
# produced from b16ac70 forward has been re-commissioned against the changed code.
#
# Flip to False -- and clear RECOMMISSIONING_NOTE to "" -- ONLY when an independent seat has
# re-fired the affected constructions against the changed code and filed a fresh decision-log
# entry citing that execution (the same discipline COMMISSIONED_SETS itself is grown under,
# module docstring above). Never as a rewording of this notice.
RECOMMISSIONING_OUTSTANDING = True
RECOMMISSIONING_NOTE = (
    "b16ac70 (TE-50, 2026-08-30) changed four commissioned components -- bm25_baseline._tokenize "
    "(the BM25 analyzer), embed_runner (the reference's query vectors), rank_score (the paired "
    "resolving power dispersion) and gate.evaluate_f2 (the verdict arithmetic) -- after every "
    "set in eval.k1.COMMISSIONED_SETS already had its own COMMISSIONED verdict filed. D-SLM5396 "
    "records the gap; D-SLM5397 defers it, explicitly 'before K1-Run-2's verdict is read as "
    "load-bearing.' No reading this instrument has produced from b16ac70 forward has been "
    "re-commissioned against the changed code (Claude/Poirot/"
    "b16ac70-te51-k1-instrument-confirmation.md Finding H-2, Wizard project records tree)."
)


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
    f"{commissioned_names_clause(s for s in COMMISSIONED_SETS if COMMISSIONING_DECISIONS.get(s) == 'D-SLM4707')} "
    "(D-SLM4707, 2026-08-25, instrument commit 3426bee; the zero-qrels guard's vitality proven "
    "on these four) and "
    f"{commissioned_names_clause(s for s in COMMISSIONED_SETS if COMMISSIONING_DECISIONS.get(s) == 'D-SLM5363')} "
    "(D-SLM5363, 2026-08-30, on a content-distance-aware remedy "
    "construction for must-reject 2, after a first attempt -- D-SLM5338 -- returned NOT "
    "COMMISSIONED on the original construction). See eval.k1.COMMISSIONING_DECISIONS for the "
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
