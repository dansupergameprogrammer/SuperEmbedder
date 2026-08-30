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
tree, D-SLM4707) returned **COMMISSIONED**: all three constructions fire correctly on all
four originally-locked sets (SciFact, NFCorpus, FiQA-2018, ArguAna) at instrument commit
`3426bee`, and the zero-qrels guard's vitality is proven. Readings this instrument produces
from that commit forward are load-bearing, **subject to the design's own re-commissioning
rule** (same document, §5): any subsequent change to the loader, ranker, scorer, or guard
requires the constructions it touches to be re-fired before a new reading from the changed
code is trusted. This is the ONE place that status is asserted; every other reference in this
package points back here rather than restating it, so a future status change is one edit, not
a search. Every entry point in this package prints this notice before emitting a result.
"""

COMMISSIONING_NOTICE = (
    "U-K1 INSTRUMENT -- COMMISSIONED (D-SLM4707, 2026-08-25, instrument commit 3426bee). "
    "All three commissioning constructions (must-accept, must-reject 1, must-reject 2) fire "
    "correctly on all four originally-locked sets (SciFact, NFCorpus, FiQA-2018, ArguAna); "
    "the zero-qrels guard's vitality is proven. Readings from this instrument are "
    "load-bearing, subject to the design's own re-commissioning rule: any subsequent change "
    "to the loader, ranker, scorer, or guard requires the affected constructions to be "
    "re-fired before a new reading from the changed code is trusted "
    "(Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md, Wizard project records "
    "tree)."
)
