"""Tests for the component re-commissioning gap's derivation (TE-53 review, J-1 (Significant)
/ J-2 (Significant), `Claude/Poirot/8d810ad-te53-k1-instrument-confirmation2.md`, Wizard
project records tree; TE-55 review, K-2 (Significant),
`Claude/Poirot/6317e68-te55-k1-instrument-confirmation3.md`).

The class this closes, per the TE-54 brief: a constant, flag or notice asserting a fact the
code could derive from git history, correct when written and silently wrong afterwards. J-1
found the hand-typed note incomplete about the very commit that authored it (it named
`b16ac70`'s four changed components while the commit carrying the note itself changed four
more of the same modules). J-2 found the root: the flag was asserted, not derived, so nothing
would re-arm it once an independent seat correctly cleared it. TE-54 derived both from git --
but scoped the query to `<baseline>..HEAD`, comparing two COMMITTED trees, so a commissioned
component modified (or newly created) in the working tree and never committed read as clear.
TE-55's K-2 found it: the instrument runs from the working tree, not from HEAD, which is
exactly the state every round of this lineage edits and re-runs in before committing.

`eval.k1._derive_recommissioning_gap` computes the gap via two distinct functions, deliberately
not one:

- `_component_files_changed_since(baseline)` -- the LIVE query, working-tree aware: `baseline`
  vs. the actual current state (committed history, uncommitted modifications, and untracked
  new files, over `COMMISSIONED_COMPONENT_FILES`). This is the only function
  `_derive_recommissioning_gap` calls.
- `_component_files_changed_between(commit_a, commit_b)` -- a pure `commit_a..commit_b` diff
  between two COMMITTED trees, used ONLY by the historical-reproduction tests below, so a fixed
  historical span stays fixed rather than silently becoming working-tree-sensitive.

These tests are in three layers:

- **Unit tests of the derivation's branch logic**, against a stubbed git query, so the
  outstanding/clear/unavailable branches are each exercised without depending on this
  repository's actual history.
- **Execution against this repository's real, fixed historical commits**, reproducing the
  exact population TE-53's review found -- the step this ticket's brief requires before any
  fix is trusted: a structure shown able to fire on one author-chosen case is not shown to
  cover the class.
- **Execution against a disposable scratch git repository**, proving K-2's fix directly: an
  uncommitted modification to a commissioned component, and an untracked new one, are each
  caught."""
from __future__ import annotations

import subprocess

import pytest

import eval.k1 as k1


def _run_git(args, cwd):
    """Runs `git <args>` in `cwd` (a disposable scratch repository) and returns stdout,
    asserting success -- never run against this source tree."""
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


# ----------------------------------------------------------------------------------------
# Unit tests: the derivation's branch logic, against a stubbed component-file query.
# ----------------------------------------------------------------------------------------


def test_no_changes_anywhere_is_not_outstanding(monkeypatch):
    """The sibling of `uncommissioned_required_sets`'s own empty case: a decision id whose
    component files have not changed since its own baseline contributes nothing, and a result
    with no problems and no changes is (False, "") -- re-armable, not stuck at True forever."""
    monkeypatch.setattr(k1, "COMMISSIONING_DECISIONS", {"scifact": "D-TEST"})
    monkeypatch.setattr(k1, "COMMISSIONED_AT_COMMIT", {"D-TEST": "deadbeef"})
    monkeypatch.setattr(k1, "_component_files_changed_since", lambda commit: [])
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
        lambda commit: ["eval/k1/gate.py"] if commit == "old-baseline" else [],
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

    def _raise(commit):
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
        lambda commit: ["eval/k1/guards.py"] if commit == "stale-baseline" else [],
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
    """TE-55 review, K-6 (Observation): must catch the same exception classes the production
    queries do (`(OSError, subprocess.SubprocessError)`) -- `subprocess.TimeoutExpired` is a
    `SubprocessError`, NOT an `OSError`, so a hung `git` used to become a collection-time error
    here instead of the clean skip this helper exists to produce. Also checks the exit code
    rather than assuming success from a returned CompletedProcess."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


requires_git = pytest.mark.skipif(not _git_available(), reason="git binary not on PATH")


# The seven-file component tuple as it stood at 6317e68 (TE-55's own review target), before
# K-1's fix completed it to the design's real fifteen-file component set. Fixed here as a
# LITERAL list -- not `k1.COMMISSIONED_COMPONENT_FILES` -- so the two historical-reproduction
# tests below keep pinning the same historical fact regardless of how the live tuple grows
# (TE-55 review, K-4 (Minor)).
_SEVEN_FILE_TUPLE_AT_6317E68 = (
    "eval/k1/bm25_baseline.py",
    "eval/k1/embed_runner.py",
    "eval/k1/gate.py",
    "eval/k1/guards.py",
    "eval/k1/rank_score.py",
    "eval/k1/runner.py",
    "eval/k1/sets_lock.py",
)


@requires_git
def test_reproduces_j1_exactly_the_four_files_named_in_the_finding():
    """J-1's own executed evidence: `git diff --name-only b16ac70..8d810ad` over the
    commissioned-component modules (as they stood at that time) returns exactly four files.
    Reproduced here through the package's own pure historical-comparison function rather than
    re-typed as a separate claim. Scoped to the FIXED historical seven-file list (K-4), not the
    live, growing `COMMISSIONED_COMPONENT_FILES`."""
    changed = k1._component_files_changed_between(
        "b16ac70", "8d810ad", component_files=_SEVEN_FILE_TUPLE_AT_6317E68,
    )
    assert changed == [
        "eval/k1/embed_runner.py",
        "eval/k1/gate.py",
        "eval/k1/guards.py",
        "eval/k1/runner.py",
    ]


@requires_git
def test_reproduces_j1s_wider_query_all_seven_from_the_original_commissioning_commit():
    """J-1's own verification log: 'the same query over 3426bee..8d810ad returns all seven.'
    Reproduced against the LITERAL seven names the finding actually cited (TE-55 review, K-4
    (Minor)) -- not `sorted(k1.COMMISSIONED_COMPONENT_FILES)`, which is what this test asserted
    before K-4: the left side is a fixed historical fact and the right side is a constant whose
    own comment says it grows, so the two are equal only by coincidence and the assertion
    breaks the moment a component is added that did not happen to change in this one historical
    span -- exactly what K-1's own completion of the tuple does (`pooling.py` and
    `self_exclusion.py` did not change between `3426bee` and `8d810ad`, and eight more of the
    fifteen live components didn't exist yet). Pinning the literal names, and the pathspec that
    produced them, lets the live component tuple vary freely without this test regressing."""
    changed = k1._component_files_changed_between(
        "3426bee", "8d810ad", component_files=_SEVEN_FILE_TUPLE_AT_6317E68,
    )
    assert changed == sorted(_SEVEN_FILE_TUPLE_AT_6317E68)


@requires_git
def test_a_decisions_own_baseline_is_a_true_baseline_not_a_stale_one():
    """SCIDOCS's own commissioning baseline (D-SLM5363, `263a750`) postdates the SET_REGISTRY
    change `sets_lock.py` carried -- so diffing from `263a750` must NOT re-flag that file,
    unlike diffing from the older four-set baseline (`3426bee`), which does. This is what makes
    per-decision baselines (rather than one global baseline) correct: a set's own gap is scoped
    to changes since ITS OWN commissioning, not since the earliest one on record. Scoped to the
    fixed historical seven-file list (K-4), same reasoning as the two tests above."""
    from_scidocs_baseline = k1._component_files_changed_between(
        "263a750", "8d810ad", component_files=_SEVEN_FILE_TUPLE_AT_6317E68,
    )
    from_four_set_baseline = k1._component_files_changed_between(
        "3426bee", "8d810ad", component_files=_SEVEN_FILE_TUPLE_AT_6317E68,
    )
    assert "eval/k1/sets_lock.py" not in from_scidocs_baseline
    assert "eval/k1/sets_lock.py" in from_four_set_baseline


@requires_git
def test_self_diff_is_always_empty_the_re_arm_condition_is_reachable_on_real_git():
    """A decision id whose baseline is HEAD itself has, by construction, zero component
    changes since its own commissioning -- the real-git counterpart of
    `test_this_is_the_re_arm_j2_asked_for` above, proving the "clear" branch is reachable
    through the actual subprocess path, not only through a stub. Uses the LIVE
    (working-tree-aware) function, not the historical one -- this is what the real derivation
    actually calls, and the worktree's own untracked paths at the time of this suite's
    authorship (`_te41_step2_must_accept_cpu.py`, `eval/k1/te50_output/`) are not among
    `COMMISSIONED_COMPONENT_FILES`, so they cannot make this non-empty."""
    assert k1._component_files_changed_since("HEAD") == []


@requires_git
def test_component_files_changed_since_catches_an_uncommitted_modification(tmp_path):
    """TE-55 review, K-2 (Significant), the defect itself reproduced and proven fixed: a
    commissioned component modified and left UNCOMMITTED must not read as clear. Executed in a
    disposable scratch repository (never in this source tree) -- the exact shape every round of
    this lineage runs in: edit a component, run the instrument, commit later."""
    repo = tmp_path / "scratch"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "Test"], cwd=repo)
    component = repo / "eval" / "k1" / "rank_score.py"
    component.parent.mkdir(parents=True)
    component.write_text("K = 1\n", encoding="utf-8")
    _run_git(["add", "-A"], cwd=repo)
    _run_git(["commit", "-q", "-m", "baseline"], cwd=repo)
    baseline = _run_git(["rev-parse", "HEAD"], cwd=repo).strip()

    orig_root = k1._REPO_ROOT
    try:
        k1._REPO_ROOT = repo
        assert k1._component_files_changed_since(baseline) == []  # nothing changed yet
        component.write_text("K = 999  # UNCOMMITTED\n", encoding="utf-8")
        changed = k1._component_files_changed_since(baseline)
    finally:
        k1._REPO_ROOT = orig_root
    assert changed == ["eval/k1/rank_score.py"]


@requires_git
def test_component_files_changed_since_catches_an_untracked_new_component_file(tmp_path):
    """The second half of K-2: an entirely new, never-committed component file -- exactly how
    `porter_stemmer.py` entered this package in `b16ac70` -- must also read as changed. A
    tracked-file diff alone (even without `..HEAD`) cannot see a file `git` has never heard of;
    `git status --porcelain` is what catches it."""
    repo = tmp_path / "scratch2"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo)
    _run_git(["config", "user.name", "Test"], cwd=repo)
    (repo / "eval" / "k1").mkdir(parents=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _run_git(["add", "-A"], cwd=repo)
    _run_git(["commit", "-q", "-m", "baseline"], cwd=repo)
    baseline = _run_git(["rev-parse", "HEAD"], cwd=repo).strip()

    new_component = repo / "eval" / "k1" / "porter_stemmer.py"
    new_component.write_text("STEM = 1\n", encoding="utf-8")  # never `git add`ed

    orig_root = k1._REPO_ROOT
    try:
        k1._REPO_ROOT = repo
        changed = k1._component_files_changed_since(baseline)
    finally:
        k1._REPO_ROOT = orig_root
    assert changed == ["eval/k1/porter_stemmer.py"]


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
