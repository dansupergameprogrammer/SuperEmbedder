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

from eval.k1 import (
    COMMISSIONED_SETS,
    COMMISSIONING_DECISIONS,
    COMMISSIONING_NOTICE,
    RECOMMISSIONING_NOTE,
    RECOMMISSIONING_OUTSTANDING,
    SET_DISPLAY_NAMES,
    _recommissioning_clause,
    commissioned_names_clause,
)
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
    """TE-53 review, J-8 (Observation): this test's docstring and hardcoded five-name list
    used to describe the property `test_the_notices_own_load_bearing_clause_is_generated_from_
    commissioned_sets` below now actually checks (a set removed from `COMMISSIONED_SETS` is
    mechanically absent from the notice) -- while itself remaining a hardcoded prose list that
    cannot fail on an over-broad claim, since it was written before the notice's name list was
    generated. What this test actually pins, correctly if narrowly: today's real, filed
    commissioned roster (all five currently-locked sets) is named in today's real notice text,
    and the notice states "load-bearing" at all. It is not a check that the notice EXCLUDES
    anything -- that property belongs to the mechanism test below."""
    assert "load-bearing" in COMMISSIONING_NOTICE
    for name in ("SciFact", "NFCorpus", "FiQA-2018", "ArguAna", "SCIDOCS"):
        assert name in COMMISSIONING_NOTICE


def test_commissioned_sets_is_a_subset_of_the_locked_set_roster():
    assert set(COMMISSIONED_SETS).issubset(set(ALL_LOCKED_SETS))


def test_commissioned_sets_now_includes_scidocs():
    """Pins today's actual commissioning state. TE-41 (D-SLM5338) first returned NOT
    COMMISSIONED for SCIDOCS -- this test, at that time, pinned the resulting gap
    (`set(ALL_LOCKED_SETS) - set(COMMISSIONED_SETS) == {"scidocs"}`). TE-46 built and
    executed a remedy construction and re-verdicted COMMISSIONED (D-SLM5363); TE-47 landed
    that verdict here. The gap this test pinned before is now closed -- updated alongside
    eval.k1.COMMISSIONED_SETS as part of that landing, not silently left asserting a stale
    state."""
    assert "scidocs" in COMMISSIONED_SETS
    assert set(ALL_LOCKED_SETS) - set(COMMISSIONED_SETS) == set()


# --------------------------------------------------------------------------------------
# H-11 (Minor, TE-51 review): the test above previously asserted five hardcoded display
# names appear in the notice -- a check COMMISSIONED_SETS == ALL_LOCKED_SETS (post-TE-47)
# satisfies exactly as readily as it would satisfy a genuinely over-broad claim, so it could
# no longer fail on the property it was written to catch. Pins the MECHANISM instead:
# commissioned_names_clause is driven by its argument, so a set removed from the commissioned
# cell is mechanically absent from the clause it would produce, not merely absent from a
# hand-maintained prose list someone remembered to edit.
# --------------------------------------------------------------------------------------


def test_commissioned_names_clause_excludes_a_set_removed_from_its_argument():
    narrowed = tuple(s for s in COMMISSIONED_SETS if s != "scidocs")
    clause = commissioned_names_clause(narrowed)
    assert SET_DISPLAY_NAMES["scidocs"] not in clause
    for s in narrowed:
        assert SET_DISPLAY_NAMES[s] in clause


def test_commissioned_names_clause_includes_every_set_present_in_its_argument():
    clause = commissioned_names_clause(COMMISSIONED_SETS)
    for s in COMMISSIONED_SETS:
        assert SET_DISPLAY_NAMES[s] in clause


def test_the_notices_own_load_bearing_clause_is_generated_from_commissioned_sets():
    """The real notice's own name list is built by commissioned_names_clause over
    COMMISSIONED_SETS (grouped by decision id), not typed by hand -- so the mechanism the two
    tests above pin is the SAME code path that produced today's real notice text, not a
    parallel implementation that happens to agree with it today."""
    for s in COMMISSIONED_SETS:
        assert SET_DISPLAY_NAMES[s] in COMMISSIONING_NOTICE


# --------------------------------------------------------------------------------------
# J-7 (Observation, TE-53 review): the notice built its two load-bearing clauses by filtering
# COMMISSIONED_SETS against two literal decision-id strings ('D-SLM4707', 'D-SLM5363'). A set
# commissioned under a THIRD decision id -- how every future commissioning arrives, since each
# is filed as its own decision-log entry -- matched neither filter and the notice built
# cleanly while silently omitting it. `_commissioning_clauses_by_decision` groups by the LIVE
# mapping instead, so a new decision id is included by construction.
# --------------------------------------------------------------------------------------


def test_a_set_commissioned_under_a_third_decision_id_is_not_silently_omitted(monkeypatch):
    """Reproduces J-7's exact failure shape and proves the fix: a made-up sixth set,
    commissioned under a decision id that is neither of the two the old code filtered on
    literally, must still get its own clause -- generated, not omitted."""
    import eval.k1 as k1_mod

    decisions_with_third_id = {**COMMISSIONING_DECISIONS, "trec-covid": "D-NEW-THIRD-ID"}
    names_with_new_set = {**SET_DISPLAY_NAMES, "trec-covid": "TREC-COVID"}
    monkeypatch.setattr(k1_mod, "COMMISSIONING_DECISIONS", decisions_with_third_id)
    monkeypatch.setattr(k1_mod, "SET_DISPLAY_NAMES", names_with_new_set)

    rendered = k1_mod._commissioning_clauses_by_decision(
        ("scifact", "nfcorpus", "fiqa", "arguana", "scidocs", "trec-covid")
    )
    assert "D-NEW-THIRD-ID" in rendered
    assert "TREC-COVID" in rendered
    # The pre-fix failure mode: the notice built cleanly and simply dropped the set. Confirm
    # the other two groups are still present too -- the fix adds coverage, it does not trade
    # one group's presence for another's.
    assert "D-SLM4707" in rendered
    assert "D-SLM5363" in rendered


# --------------------------------------------------------------------------------------
# H-2 (Critical, TE-51 review): the notice stated the general re-commissioning RULE but not
# that it is CURRENTLY outstanding -- D-SLM5396 records the gap, D-SLM5397 defers it, and a
# reader of the notice alone had no way to learn either. Pins the mechanism (both branches of
# _recommissioning_clause) and today's real, filed state separately.
# --------------------------------------------------------------------------------------


def test_recommissioning_clause_is_present_when_outstanding():
    text = _recommissioning_clause(True, "the gap text")
    assert "OUTSTANDING" in text
    assert "the gap text" in text


def test_recommissioning_clause_is_empty_when_not_outstanding():
    assert _recommissioning_clause(False, "the gap text") == ""


def test_todays_real_notice_states_the_outstanding_recommissioning_gap():
    """TE-53 review, J-1/J-2: RECOMMISSIONING_OUTSTANDING is now DERIVED
    (`eval.k1._derive_recommissioning_gap`, pinned on its own branch logic and against real
    historical commits in `test_recommissioning_gap.py`), not hand-set -- so this pin must not
    merely assert today's value is `True`, which is exactly the shape of claim that goes stale
    silently (that IS J-2). It instead recomputes the fact independently, via a real git query
    over each commissioned decision's own baseline, and checks the module's computed value
    against that recomputation -- so this test fails the day the module's own derivation
    disagrees with the repository's real history, in either direction."""
    from eval.k1 import COMMISSIONED_AT_COMMIT, COMMISSIONING_DECISIONS, _component_files_changed_since

    any_component_changed_since_its_own_baseline = False
    for decision_id in set(COMMISSIONING_DECISIONS.values()):
        baseline = COMMISSIONED_AT_COMMIT[decision_id]
        if _component_files_changed_since(baseline, "HEAD"):
            any_component_changed_since_its_own_baseline = True

    assert RECOMMISSIONING_OUTSTANDING is any_component_changed_since_its_own_baseline
    if any_component_changed_since_its_own_baseline:
        assert "OUTSTANDING" in COMMISSIONING_NOTICE
        assert RECOMMISSIONING_NOTE in COMMISSIONING_NOTICE
    else:
        assert "OUTSTANDING" not in COMMISSIONING_NOTICE


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
