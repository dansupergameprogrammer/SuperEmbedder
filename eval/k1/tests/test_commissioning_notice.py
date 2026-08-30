"""Tests for ``eval.k1.COMMISSIONING_NOTICE`` and ``eval.k1.COMMISSIONED_SETS`` (TE-40 code
review, Finding F-1 (Critical), `Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard
project records tree).

The commissioning spec's disposition rule
(`Claude/Mendeleev/u-k1-commissioning-2026-08-25.md` Section 5) carries two independent
triggers: a construction firing does not validate a **different, unexecuted configuration**
(e.g. a newly-added set), and separately, a **component** change (loader/ranker/scorer/guard)
requires the constructions it touches to be re-fired. Before this fix, the notice transcribed
only the component trigger, so adding SCIDOCS to the gate's required-set conjunction (TE-40)
-- a configuration change, not a component change -- could not be caught by the notice's own
wording. These tests pin that the configuration trigger is present, generically (not naming
SCIDOCS specifically, since the notice's own author does not get to assert SCIDOCS's
commissioning verdict -- that is executed and logged independently)."""
from __future__ import annotations

from pathlib import Path

from eval.k1 import COMMISSIONED_SETS, COMMISSIONING_NOTICE
from eval.k1.set_roster import ALL_LOCKED_SETS

README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def test_notice_restores_the_configuration_half_of_the_disposition_rule():
    """The dropped sentence, restored: a construction that fires does not retroactively
    validate a different, unexecuted configuration."""
    assert "unexecuted configuration" in COMMISSIONING_NOTICE


def test_notice_still_carries_the_component_half_of_the_disposition_rule():
    """The pre-existing half must survive the fix -- both triggers are independent and both
    are required, per the disposition rule's own two sentences."""
    assert "loader" in COMMISSIONING_NOTICE
    assert "ranker" in COMMISSIONING_NOTICE
    assert "scorer" in COMMISSIONING_NOTICE
    assert "guard" in COMMISSIONING_NOTICE
    assert "re-fired" in COMMISSIONING_NOTICE


def test_notice_names_the_commissioned_sets_constant_rather_than_a_bare_set_list():
    """The notice must route a reader to eval.k1.COMMISSIONED_SETS (the live, checkable cell)
    rather than only a prose list -- so a future commissioning of another set updates the
    constant and the notice's own claim stays correct without a second edit to this string."""
    assert "COMMISSIONED_SETS" in COMMISSIONING_NOTICE


def test_notice_does_not_claim_load_bearing_across_every_locked_set():
    """The notice's load-bearing claim must be scoped to the commissioned cell, not asserted
    as a blanket statement across every set the roster locks."""
    assert "load-bearing" in COMMISSIONING_NOTICE
    # The blanket pre-fix phrasing asserted load-bearing status unconditionally; the fixed
    # text must qualify it to the four commissioned sets, named explicitly in the notice.
    for name in ("SciFact", "NFCorpus", "FiQA-2018", "ArguAna"):
        assert name in COMMISSIONING_NOTICE


def test_commissioned_sets_is_a_subset_of_the_locked_set_roster():
    assert set(COMMISSIONED_SETS).issubset(set(ALL_LOCKED_SETS))


def test_commissioned_sets_does_not_yet_include_scidocs():
    """Pins today's actual commissioning state (D-SLM4707 execution3 Section 7: "four sets").
    SCIDOCS's own commissioning is executed and logged independently (TE-41); when that
    lands, this test is updated alongside eval.k1.COMMISSIONED_SETS as part of that
    dispatch -- not silently left asserting a stale gap."""
    assert "scidocs" not in COMMISSIONED_SETS
    assert set(ALL_LOCKED_SETS) - set(COMMISSIONED_SETS) == {"scidocs"}


def test_readme_carries_the_notices_configuration_scoping_clause():
    """F-15 (Observation, TE-40 review, `Claude/Poirot/41424b0-te40-k1-instrument-review.md`):
    ``eval/k1/README.md``'s Commissioning section restates the same disposition rule
    ``COMMISSIONING_NOTICE`` asserts, and no test in this suite referenced the README, so the
    two could drift silently. TE-44 review, G-6: F-15 was still unclosed at the confirmation
    pass, and the README's restatement had grown (one paragraph to two, plus a second
    expanded restatement further down) in the same round that left it unpinned. Pins the one
    clause distinguishing the fix this notice carries -- a construction firing does not
    retroactively validate a different, unexecuted configuration -- present in both."""
    assert "unexecuted configuration" in COMMISSIONING_NOTICE
    readme_text = README_PATH.read_text(encoding="utf-8")
    assert "unexecuted configuration" in readme_text
