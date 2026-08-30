"""Tests for ``eval/k1/run_spec.py`` (TE-40 code review, Finding F-8 (Minor),
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree).

``RunSpec.is_gate_reading``'s own comment asserted, in a file this diff itself edited, that a
Run 1 reading is "still quarantined pending commissioning" -- a blanket claim the same diff's
own status-constant fix (COMMISSIONING_NOTICE -> COMMISSIONED) had already superseded for
four of the five required sets. A tree-wide grep for "quarantin" returns six other,
legitimate hits (the constant's own migration path, a historical quotation, the legacy-key
fallbacks); this one asserted a superseded verdict as present fact."""
from __future__ import annotations

import inspect

import eval.k1.run_spec as run_spec_mod


def test_run_spec_no_longer_asserts_a_blanket_still_quarantined_claim():
    source = inspect.getsource(run_spec_mod)
    assert "still quarantined pending commissioning" not in source


def test_run_spec_reexports_the_roster_from_set_roster_unchanged():
    """The re-export this fix depends on (F-7's leaf module) must keep every existing
    run_spec.PUBLIC_SETS / run_spec.ALL_LOCKED_SETS reference working."""
    from eval.k1.set_roster import ALL_LOCKED_SETS, INTERNAL_DIAGNOSTIC_SETS, PUBLIC_SETS

    assert run_spec_mod.PUBLIC_SETS == PUBLIC_SETS
    assert run_spec_mod.INTERNAL_DIAGNOSTIC_SETS == INTERNAL_DIAGNOSTIC_SETS
    assert run_spec_mod.ALL_LOCKED_SETS == ALL_LOCKED_SETS
