"""Tests for the component re-commissioning gap's derivation (TE-53 review, J-1 (Significant)
/ J-2 (Significant), `Claude/Poirot/8d810ad-te53-k1-instrument-confirmation2.md`, Wizard
project records tree).

The class this closes, per the TE-54 brief: a constant, flag or notice asserting a fact the
code could derive from HEAD, correct when written and silently wrong afterwards. Four
instances were found across three review rounds of this instrument; this is the fourth and
last still open. `eval.k1.RECOMMISSIONING_OUTSTANDING` and `RECOMMISSIONING_NOTE` used to be a
hand-set boolean and a hand-typed string naming which commissioned-component modules changed
since which commissioning baseline. J-1 found the hand-typed note incomplete about the very
commit that authored it (it named `b16ac70`'s four changed components while the commit
carrying the note itself changed four more of the same modules). J-2 found the root: the flag
was asserted, not derived, so nothing would re-arm it once an independent seat correctly
cleared it -- the next component change after a re-commissioning would ship with the flag
silently reading `False` again.

`eval.k1._derive_recommissioning_gap` replaces both with one computation:
`git diff --name-only <decision's own commissioning baseline>..HEAD`, scoped to
`COMMISSIONED_COMPONENT_FILES`, grouped by decision id. These tests are in two layers:

- **Unit tests of the derivation's branch logic**, against a stubbed git query, so the
  outstanding/clear/unavailable branches are each exercised without depending on this
  repository's actual history.
- **Execution against this repository's real, fixed historical commits**, reproducing the
  exact population TE-53's review found -- the step this ticket's brief requires before any
  fix is trusted: a structure shown able to fire on one author-chosen case is not shown to
  cover the class."""
from __future__ import annotations

import subprocess

import pytest

import eval.k1 as k1


# ----------------------------------------------------------------------------------------
# Unit tests: the derivation's branch logic, against a stubbed component-file query.
# ----------------------------------------------------------------------------------------


def test_no_changes_anywhere_is_not_outstanding(monkeypatch):
    """The sibling of `uncommissioned_required_sets`'s own empty case: a decision id whose
    component files have not changed since its own baseline contributes nothing, and a result
    with no problems and no changes is (False, "") -- re-armable, not stuck at True forever."""
    monkeypatch.setattr(k1, "COMMISSIONING_DECISIONS", {"scifact": "D-TEST"})
    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {"D-TEST": "deadbeef"})
    monkeypatch.setattr(k1, "_component_files_changed_since", lambda commit, to_ref="HEAD": [])
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is False
    assert note == ""


def test_this_is_the_re_arm_j2_asked_for(monkeypatch):
    """J-2's own complaint: 'nothing re-arms it once it is correctly cleared.' Simulates
    exactly that lifecycle in one call -- a decision id whose component files changed since its
    OLD baseline (outstanding), then the same decision id with its baseline updated to a point
    after the change (clear) -- proving the mechanism itself re-arms, which a hand-set boolean
    structurally cannot."""
    monkeypatch.setattr(k1, "COMMISSIONING_DECISIONS", {"scifact": "D-TEST"})

    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {"D-TEST": "old-baseline"})
    monkeypatch.setattr(
        k1, "_component_files_changed_since",
        lambda commit, to_ref="HEAD": ["eval/k1/gate.py"] if commit == "old-baseline" else [],
    )
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is True
    assert "D-TEST" in note
    assert "eval/k1/gate.py" in note

    # An independent seat re-fires and files a fresh decision-log entry citing a new baseline
    # commit -- the ONLY sanctioned way to clear the gap (module docstring). Nothing else in
    # this test changed.
    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {"D-TEST": "new-baseline"})
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is False
    assert note == ""


def test_a_decision_with_no_baseline_is_outstanding_and_unverified(monkeypatch):
    """A decision id present in COMMISSIONING_DECISIONS but absent from COMMISSIONED_AT_COMMIT
    cannot be checked at all -- folded into the result as outstanding, with the gap named as
    unverified rather than silently treated as clear."""
    monkeypatch.setattr(k1, "COMMISSIONING_DECISIONS", {"scifact": "D-NO-BASELINE"})
    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {})
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is True
    assert "UNVERIFIED" in note
    assert "D-NO-BASELINE" in note


def test_a_git_query_that_cannot_run_is_outstanding_and_unverified(monkeypatch):
    """`_component_files_changed_since` raising `_RecommissioningCheckUnavailable` (no git
    binary, this directory not a checkout, or a cited commit unreachable -- e.g. a shallow
    clone) is folded into the result as outstanding rather than allowed to propagate as a bare
    exception or silently read as clear."""
    monkeypatch.setattr(k1, "COMMISSIONING_DECISIONS", {"scifact": "D-TEST"})
    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {"D-TEST": "unreachable-commit"})

    def _raise(commit, to_ref="HEAD"):
        raise k1._RecommissioningCheckUnavailable("git could not resolve unreachable-commit")

    monkeypatch.setattr(k1, "_component_files_changed_since", _raise)
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is True
    assert "UNVERIFIED" in note
    assert "unreachable-commit" in note


def test_two_decisions_one_outstanding_one_clear(monkeypatch):
    """The overall result is outstanding if ANY commissioned decision's own component set
    changed since ITS OWN baseline -- a clear decision does not mask an outstanding one, and
    the note names only the decision(s) that are actually outstanding."""
    monkeypatch.setattr(
        k1, "COMMISSIONING_DECISIONS", {"scifact": "D-CLEAR", "scidocs": "D-OUTSTANDING"},
    )
    monkeypatch.setattr(
        k1, "COMMISSIONED_AT_COMMIT", {"D-CLEAR": "clear-baseline", "D-OUTSTANDING": "stale-baseline"},
    )
    monkeypatch.setattr(
        k1, "_component_files_changed_since",
        lambda commit, to_ref="HEAD": ["eval/k1/guards.py"] if commit == "stale-baseline" else [],
    )
    outstanding, note = k1._derive_recommissioning_gap()
    assert outstanding is True
    assert "D-OUTSTANDING" in note
    assert "D-CLEAR" not in note


# ----------------------------------------------------------------------------------------
# Execution against this repository's real, fixed historical commits -- the population TE-53's
# review found, reproduced rather than asserted. Every commit cited below is real history on
# this branch; none depends on where HEAD is when the suite runs.
# ----------------------------------------------------------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except OSError:
        return False


requires_git = pytest.mark.skipif(not _git_available(), reason="git binary not on PATH")


@requires_git
def test_reproduces_j1_exactly_the_four_files_named_in_the_finding():
    """J-1's own executed evidence: `git diff --name-only b16ac70..8d810ad` over the
    commissioned-component modules returns exactly four files. Reproduced here through the
    package's own mechanism rather than re-typed as a separate claim."""
    changed = k1._component_files_changed_since("b16ac70", "8d810ad")
    assert changed == [
        "eval/k1/embed_runner.py",
        "eval/k1/gate.py",
        "eval/k1/guards.py",
        "eval/k1/runner.py",
    ]


@requires_git
def test_reproduces_j1s_wider_query_all_seven_from_the_original_commissioning_commit():
    """J-1's own verification log: 'the same query over 3426bee..8d810ad returns all seven.'
    Reproduced: every file in COMMISSIONED_COMPONENT_FILES changed somewhere in that span."""
    changed = k1._component_files_changed_since("3426bee", "8d810ad")
    assert changed == sorted(k1.COMMISSIONED_COMPONENT_FILES)


@requires_git
def test_a_decisions_own_baseline_is_a_true_baseline_not_a_stale_one():
    """SCIDOCS's own commissioning baseline (D-SLM5363, `263a750`) postdates the SET_REGISTRY
    change `sets_lock.py` carried -- so diffing from `263a750` must NOT re-flag that file,
    unlike diffing from the older four-set baseline (`3426bee`), which does. This is what makes
    per-decision baselines (rather than one global baseline) correct: a set's own gap is scoped
    to changes since ITS OWN commissioning, not since the earliest one on record."""
    from_scidocs_baseline = k1._component_files_changed_since("263a750", "8d810ad")
    from_four_set_baseline = k1._component_files_changed_since("3426bee", "8d810ad")
    assert "eval/k1/sets_lock.py" not in from_scidocs_baseline
    assert "eval/k1/sets_lock.py" in from_four_set_baseline


@requires_git
def test_self_diff_is_always_empty_the_re_arm_condition_is_reachable_on_real_git():
    """A decision id whose baseline is HEAD itself has, by construction, zero component
    changes since its own commissioning -- the real-git counterpart of
    `test_this_is_the_re_arm_j2_asked_for` above, proving the "clear" branch is reachable
    through the actual subprocess path, not only through a stub."""
    assert k1._component_files_changed_since("HEAD", "HEAD") == []


@requires_git
def test_todays_real_gap_is_outstanding_and_names_both_commissioning_baselines():
    """The package's own real, computed state: as of this ticket, no decision's own component
    set is clear (every commissioned decision's baseline predates ongoing K1 fix rounds that
    keep touching gate.py/guards.py/runner.py), so the derived result is outstanding and its
    note is traceable to both decisions on file -- generated, not typed."""
    assert k1.RECOMMISSIONING_OUTSTANDING is True
    assert "D-SLM4707" in k1.RECOMMISSIONING_NOTE
    assert "D-SLM5363" in k1.RECOMMISSIONING_NOTE
    assert "UNVERIFIED" not in k1.RECOMMISSIONING_NOTE  # the real git query succeeded
    assert k1.RECOMMISSIONING_NOTE in k1.COMMISSIONING_NOTICE


@requires_git
def test_commissioned_at_commit_keys_match_commissioning_decisions_values():
    """Every decision id COMMISSIONING_DECISIONS actually cites has a COMMISSIONED_AT_COMMIT
    baseline -- otherwise today's real derivation would silently fall into the
    no-baseline-is-outstanding branch instead of computing a real answer. This is the
    structural counterpart of test_commissioned_sets_pin.py's own citation-table pin."""
    assert set(k1.COMMISSIONING_DECISIONS.values()) <= set(k1.COMMISSIONED_AT_COMMIT.keys())
