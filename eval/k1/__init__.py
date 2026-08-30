"""U-K1 -- the K1 retrieval-quality gate's instrument.

Built to `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (design of record, the Wizard
project's records tree). This package is the instrument only: it loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet.

COMMISSIONING NOTICE (StandardsDocument.md 5.4, "An instrument is commissioned before its
verdicts are load-bearing -- and never by its own maker"): the commissioning constructions
(the must-accept and the two must-reject constructions named in the design's Section 6.4)
are authored by a seat independent of this instrument's builder, not by this package. An
independent seat executed those constructions three times as the instrument's build round
answered successive findings; the third execution
(`Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md`, Wizard project records
tree, D-SLM4707) returned **COMMISSIONED**: all three constructions fire correctly on the
four sets in `COMMISSIONED_SETS` below at instrument commit `3426bee`, and the zero-qrels
guard's vitality is proven. Readings this instrument produces on those four sets, from that
commit forward, are load-bearing.

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

TE-40 review, F-1 (Critical, `Claude/Poirot/41424b0-te40-k1-instrument-review.md`): the
notice below previously transcribed only the component sentence of the disposition rule.
When SCIDOCS was added to the gate's required-set conjunction (TE-40's own change), that
narrowed text could not fire on the case that produced it -- adding a fifth locked set
changes no loader, ranker, scorer, or guard, so nothing in the old notice flagged that
SCIDOCS itself had never been commissioned. This module restores the dropped configuration
sentence, generically, so it fires correctly whichever set is added next; it takes no
position on SCIDOCS's own commissioning verdict, which is executed and logged independently
(TE-41).

This is the ONE place that status is asserted; every other reference in this package points
back here rather than restating it, so a future status change is one edit, not a search.
Every entry point in this package prints this notice before emitting a result.
"""

# The set names D-SLM4707's third execution actually fired the three commissioning
# constructions against (`Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md`
# Section 7's own stated cell: "four sets (SciFact, NFCorpus, FiQA-2018, ArguAna)"). A
# locked set not in this tuple has never had its own must-accept/must-reject constructions
# fired -- see the disposition rule quoted in the module docstring above. Grows only when a
# third context executes the constructions against a newly-added set and logs the verdict as
# a decision-log entry citing the commissioning spec (`Claude/Mendeleev/
# u-k1-commissioning-2026-08-25.md` Section 5) -- never by editing this tuple to match the
# roster without that execution having happened.
COMMISSIONED_SETS = ("scifact", "nfcorpus", "fiqa", "arguana")

COMMISSIONING_NOTICE = (
    "U-K1 INSTRUMENT -- COMMISSIONED ON eval.k1.COMMISSIONED_SETS ONLY (D-SLM4707, "
    "2026-08-25, instrument commit 3426bee). All three commissioning constructions "
    "(must-accept, must-reject 1, must-reject 2) fire correctly on SciFact, NFCorpus, "
    "FiQA-2018 and ArguAna; the zero-qrels guard's vitality is proven on those four. "
    "Readings from this instrument on those four sets are load-bearing. A construction that "
    "fires does not retroactively validate a different, unexecuted configuration "
    "(commissioning spec Section 5): any other locked set -- present in "
    "eval.k1.set_roster.ALL_LOCKED_SETS but absent from eval.k1.COMMISSIONED_SETS -- has "
    "never had its own must-accept/must-reject constructions fired, and its readings stay "
    "quarantined (recorded, never acted on, never headlined, not read into any gate verdict "
    "as load-bearing) until an independent seat runs them and files the executed verdict as "
    "a decision-log entry citing the commissioning spec. Readings are ALSO subject to the "
    "design's own component re-commissioning rule, which is a separate condition: any "
    "subsequent change to the loader, ranker, scorer, or guard requires the constructions it "
    "touches to be re-fired, on every set they touch, before a new reading from the changed "
    "code is trusted "
    "(Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md and "
    "Claude/Mendeleev/u-k1-commissioning-2026-08-25.md Section 5, Wizard project records "
    "tree)."
)
