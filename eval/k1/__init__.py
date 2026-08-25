"""U-K1 -- the K1 retrieval-quality gate's instrument.

Built to `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (design of record, the Wizard
project's records tree). This package is the instrument only: it loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet.

QUARANTINE NOTICE (StandardsDocument.md 5.4, "An instrument is commissioned before its
verdicts are load-bearing -- and never by its own maker"): the commissioning constructions
(the must-accept and the two must-reject constructions named in the design's Section 6.4)
are authored by a seat independent of this instrument's builder, not by this package. Until
those three constructions are executed and fire correctly, every reading this instrument
produces is QUARANTINED -- recorded, never acted on, never headlined, and not read into any
gate verdict. Every entry point in this package prints this notice before emitting a result.
"""

QUARANTINE_NOTICE = (
    "U-K1 INSTRUMENT -- READINGS QUARANTINED. Commissioning (must-accept + two must-reject "
    "constructions, design Section 6.4) has not been executed by an independent seat. No "
    "reading emitted below is a gate verdict until that commissioning fires correctly."
)
