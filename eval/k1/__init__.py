"""U-K1 -- the K1 retrieval-quality gate's instrument.

Built to `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (design of record, the Wizard
project's records tree). This package is the instrument only: it loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet.

QUARANTINE NOTICE (StandardsDocument.md 5.4, "An instrument is commissioned before its
verdicts are load-bearing -- and never by its own maker"): the commissioning constructions
(the must-accept and the two must-reject constructions named in the design's Section 6.4)
are authored by a seat independent of this instrument's builder, not by this package. An
independent seat executed all three constructions once already
(`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md`, Wizard project records tree)
and returned NOT COMMISSIONED, blocked by two build findings (D-SLM4688, D-SLM4689) fixed in
the U-K1 fix round (`Claude/Brunel/u-k1-fix1-2026-08-25.md`). **The fix has not yet been
re-verified by a re-run of the commissioning constructions** -- per the commissioning spec's
own disposition rule, a fix to the loader or the scorer requires re-firing the constructions
it touches before any reading is load-bearing, and that re-execution is a separate dispatch
from this fix round. Until that re-run fires correctly, every reading this instrument
produces remains QUARANTINED -- recorded, never acted on, never headlined, and not read into
any gate verdict. Every entry point in this package prints this notice before emitting a
result.
"""

QUARANTINE_NOTICE = (
    "U-K1 INSTRUMENT -- READINGS QUARANTINED. Commissioning was executed once and returned "
    "NOT COMMISSIONED (build findings D-SLM4688/D-SLM4689, since fixed); the fix has not yet "
    "been verified by re-running the must-accept and both must-reject constructions "
    "(design Section 6.4) against an independent seat. No reading emitted below is a gate "
    "verdict until that re-run fires correctly."
)
