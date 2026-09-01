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
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

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


# Additional narrative context for a decision id's own commissioning clause in the notice --
# separate from COMMISSIONING_DECISIONS (which CITES the decision) so that a decision id can
# be added there and immediately get its own clause in the notice (TE-53 review, J-7) even
# before anyone has written the narrative aside for it. A decision id absent from this table
# still gets a clause -- generic rather than annotated -- never silently omitted.
COMMISSIONING_NARRATIVE = {
    "D-SLM4707": (
        "2026-08-25; the zero-qrels guard's vitality proven on this group"
    ),
    "D-SLM5363": (
        "2026-08-30, on a content-distance-aware remedy construction for must-reject 2, "
        "after a first attempt -- D-SLM5338 -- returned NOT COMMISSIONED on the original "
        "construction"
    ),
}
# TE-55 review, K-5 (Minor): this table used to embed D-SLM4707's baseline sha directly
# ("instrument commit 3426bee"), duplicating COMMISSIONED_AT_COMMIT with nothing pinning the
# two together -- so the sanctioned clearing act (D-SLM5844: file a fresh decision id, add its
# baseline to COMMISSIONED_AT_COMMIT) could move the derivation's own input while the notice
# kept printing the old sha, with a green suite. The baseline is no longer typed here at all --
# `_commissioning_clauses_by_decision` below interpolates it from `COMMISSIONED_AT_COMMIT`
# directly, so the printed commit and the queried commit cannot drift from each other.


def _commissioning_clauses_by_decision(commissioned_sets) -> str:
    """Builds one load-bearing clause per decision id actually present in
    `COMMISSIONING_DECISIONS`, grouping `commissioned_sets` by the decision that commissioned
    each -- TE-53 review, J-7 (Observation): the notice previously filtered on two literal
    decision-id strings, so a set commissioned under a THIRD id (how every future
    commissioning arrives, since each is filed as its own decision-log entry) matched neither
    filter and the notice built cleanly while silently omitting it, even though the notice's
    first sentence still asserted load-bearing standing on all of `COMMISSIONED_SETS`.
    Grouping by the live mapping instead makes a set's presence in some clause and its
    presence in `COMMISSIONED_SETS` mechanically the same fact -- the same property
    `commissioned_names_clause` already gives the name list within one clause.

    The clause's commissioning-commit annotation is read from `COMMISSIONED_AT_COMMIT`
    (TE-55 review, K-5) -- the same table `_derive_recommissioning_gap` actually queries --
    rather than from a second, hand-typed copy in `COMMISSIONING_NARRATIVE`, so the printed
    baseline and the queried baseline are mechanically the same value."""
    groups: Dict[str, List[str]] = {}
    for s in commissioned_sets:
        groups.setdefault(COMMISSIONING_DECISIONS[s], []).append(s)
    clauses = []
    for decision_id in sorted(groups):
        names = commissioned_names_clause(groups[decision_id])
        narrative = COMMISSIONING_NARRATIVE.get(decision_id)
        baseline = COMMISSIONED_AT_COMMIT.get(decision_id)
        baseline_clause = f", instrument commit {baseline}" if baseline else ""
        if narrative:
            clauses.append(f"{names} ({decision_id}{baseline_clause}, {narrative})")
        else:
            clauses.append(
                f"{names} ({decision_id}{baseline_clause} -- see "
                "eval.k1.COMMISSIONING_DECISIONS)"
            )
    return " and ".join(clauses)


# TE-53 review, J-1 (Significant) / J-2 (Significant): RECOMMISSIONING_OUTSTANDING and
# RECOMMISSIONING_NOTE used to be a hand-set boolean and a hand-typed string -- both asserted
# a fact (which commissioned-component modules changed since which set's own commissioning
# baseline) that this repository's own git history already states as data. J-1 found the
# hand-typed note incomplete about the very commit that authored it; J-2 found the root: a
# hand-set flag cannot re-arm once correctly cleared, so the NEXT component change after a
# re-commissioning would ship with the flag silently reading False again. Both close the same
# way `uncommissioned_required_sets` (TE-40 review, F-1) already closed the sibling gap for an
# uncommissioned SET: compute the fact from what actually changed, rather than typing a claim
# about it.
#
# COMMISSIONED_COMPONENT_FILES names the concrete files the disposition rule's component
# sentence ("the loader, ranker, scorer, or guard") means in this instrument -- every file
# under eval/k1/ that is not a documented exclusion (COMMISSIONED_COMPONENT_EXCLUDED_DIRS /
# COMMISSIONED_COMPONENT_EXCLUDED_FILES below) must appear here, pinned by
# eval/k1/tests/test_component_partition.py (TE-55 review, K-1 (Significant)): the seven-file
# tuple that shipped at 6317e68 omitted six of the design's own components --
# `pooling.py`, `porter_stemmer.py`, `self_exclusion.py`, `run_spec.py`, `anchors.py`,
# `anchors.json`, `set_roster.py`, `sets.lock.json` -- including `porter_stemmer.py`, 193
# lines created whole in the very commit this instrument's re-commissioning gap is about, and
# nothing compared the tuple against the package's actual files to catch it.
# COMMISSIONED_AT_COMMIT cites, per decision id, the instrument commit that decision's own
# COMMISSIONED verdict was executed against (D-SLM4707's own entry: instrument commit
# 3426bee; D-SLM5363's own entry: "fix/te40-k1-stale-truth@263a750"). D-SLM5844 rules this
# table APPEND-ONLY: a decision id's value is the commit its OWN verdict was executed against,
# fixed forever once filed, and a re-commissioning never mutates an existing key -- it files a
# NEW decision-log entry under a NEW decision id, adds that id's own baseline here, and
# re-points the affected sets' entries in COMMISSIONING_DECISIONS to the new id. That is what
# keeps a key meaning what its own filed decision-log entry says it means, rather than
# drifting to "the latest baseline for whatever this id once commissioned" after one clear.
# Both tables grow only alongside a filed verdict's own text naming the addition, never edited
# to make a real diff disappear.
COMMISSIONED_COMPONENT_FILES: Tuple[str, ...] = (
    "eval/k1/anchors.json",
    "eval/k1/anchors.py",
    "eval/k1/bm25_baseline.py",
    "eval/k1/embed_runner.py",
    "eval/k1/gate.py",
    "eval/k1/guards.py",
    "eval/k1/pooling.py",
    "eval/k1/porter_stemmer.py",
    "eval/k1/rank_score.py",
    "eval/k1/run_spec.py",
    "eval/k1/runner.py",
    "eval/k1/self_exclusion.py",
    "eval/k1/set_roster.py",
    "eval/k1/sets.lock.json",
    "eval/k1/sets_lock.py",
)

COMMISSIONED_AT_COMMIT: Dict[str, str] = {
    "D-SLM4707": "3426bee",
    "D-SLM5363": "263a750",
}

_K1_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _K1_PACKAGE_DIR.parents[1]  # eval/k1 -> eval -> repository root

# TE-55 review, K-1 (Significant): a hand-typed component tuple can only ever be checked
# against itself -- nothing compared it to the package's actual files, so a new module was
# silently out of the re-commissioning gap's scope until someone remembered to add it, exactly
# how porter_stemmer.py (created whole in b16ac70) went unseen for two rounds running. These
# two constants make that comparison possible: every regular file physically present under
# eval/k1/ must be either a commissioned component (above) or named here as a documented
# exclusion. `_partition_gap` (below) walks the real directory and returns whatever is in
# neither -- a new production module is therefore IN scope by default (it fails the partition
# test the moment it exists on disk, committed or not) rather than silently out of scope until
# someone remembers to extend a list.
COMMISSIONED_COMPONENT_EXCLUDED_DIRS: Tuple[str, ...] = (
    "tests",
    "tools",
    "smoke_output",
    "te50_output",
    "__pycache__",
)
COMMISSIONED_COMPONENT_EXCLUDED_FILES: Tuple[str, ...] = (
    "__init__.py",
    "README.md",
)


def _partition_gap(component_files=None, package_dir: Path = None) -> List[str]:
    """Returns every regular file physically present under ``eval/k1/`` that is neither a
    commissioned component (``component_files``, defaulting to the live
    ``COMMISSIONED_COMPONENT_FILES``) nor a documented exclusion
    (``COMMISSIONED_COMPONENT_EXCLUDED_DIRS`` / ``COMMISSIONED_COMPONENT_EXCLUDED_FILES``).
    Empty means the partition holds: every file is accounted for as one or the other.

    A non-empty result names exactly the files a re-commissioning gap check would silently
    never examine (TE-55 review, K-1) -- this check walks the real directory rather than
    trusting a remembered list, so a new file is caught the moment it exists, whether or not it
    has been committed.

    ``component_files`` is a parameter, defaulting to the live constant, so a test can
    reproduce a PAST enumeration's gap without the live tuple itself needing to regress --
    TE-55's own instruction: prove the check fails on the pre-fix seven-file tuple, naming the
    omitted artifacts, before it passes on the fixed one."""
    component_files = (
        COMMISSIONED_COMPONENT_FILES if component_files is None else component_files
    )
    package_dir = _K1_PACKAGE_DIR if package_dir is None else package_dir
    component_set = {Path(f).as_posix() for f in component_files}
    gap: List[str] = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(package_dir).parts
        if any(part in COMMISSIONED_COMPONENT_EXCLUDED_DIRS for part in parts[:-1]):
            continue
        if len(parts) == 1 and parts[0] in COMMISSIONED_COMPONENT_EXCLUDED_FILES:
            continue
        # Built relative to `package_dir` itself (never `_REPO_ROOT`) so a test can point this
        # at a disposable directory standing in for eval/k1/ without it needing to sit under
        # this repository's actual root -- "eval/k1" is this package's own fixed name, not a
        # derived path.
        rel = "eval/k1/" + path.relative_to(package_dir).as_posix()
        if rel in component_set:
            continue
        gap.append(rel)
    return gap


class _RecommissioningCheckUnavailable(RuntimeError):
    """Raised internally when the git query a component's re-commissioning gap depends on
    cannot be answered -- no `git` binary, this directory not a git checkout, or a cited
    baseline commit unreachable (e.g. a shallow clone). Never escapes
    `_derive_recommissioning_gap`: caught there and folded into an outstanding result, because
    a check that could not run is not evidence of a clear one."""


def _component_files_changed_between(
    commit_a: str, commit_b: str, component_files=None,
) -> List[str]:
    """Runs `git diff --name-only <commit_a>..<commit_b>`, scoped to `component_files`
    (defaulting to the live `COMMISSIONED_COMPONENT_FILES`), from the repository this package
    is checked out in -- a pure comparison between two COMMITTED trees, for reproducing a
    historical fact (e.g. "what changed between these two shipped commits"). Never called by
    the live derivation (`_derive_recommissioning_gap` uses `_component_files_changed_since`
    below, which is working-tree aware); this exists so a test can pin a fixed historical span
    without that span silently becoming working-tree-sensitive.

    `component_files` is an explicit parameter, not only the live default, for the same reason
    `_partition_gap` takes one (TE-55 review, K-4 (Minor)): a test reproducing what changed in
    a FIXED historical span between two FIXED commits is pinning a historical fact, and that
    fact must not silently change shape merely because `COMMISSIONED_COMPONENT_FILES` grows --
    which it is designed to do. Passing the literal historical file list keeps the historical
    pin fixed while the live constant still varies freely.

    Raises `_RecommissioningCheckUnavailable` -- never a bare subprocess exception -- on any
    failure."""
    component_files = (
        COMMISSIONED_COMPONENT_FILES if component_files is None else component_files
    )
    try:
        result = subprocess.run(
            [
                "git", "diff", "--name-only", f"{commit_a}..{commit_b}",
                "--", *component_files,
            ],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RecommissioningCheckUnavailable(f"git diff could not run: {exc}") from exc
    if result.returncode != 0:
        raise _RecommissioningCheckUnavailable(
            f"git diff --name-only {commit_a}..{commit_b} exited {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _component_files_changed_since(commit: str) -> List[str]:
    """The live derivation's own query (TE-55 review, K-2 (Significant)): every
    `COMMISSIONED_COMPONENT_FILES` path that differs between `<commit>` and the ACTUAL CURRENT
    STATE OF THE WORKING TREE -- committed history since `<commit>`, PLUS any staged or
    unstaged modification not yet committed, PLUS any of those paths that is untracked (new,
    never committed).

    This replaces the prior `<commit>..HEAD` form, which compares two COMMITTED trees and is
    therefore blind to exactly the state this instrument actually runs from: the working tree.
    Executed proof of the gap this closes (K-2, in a disposable scratch repository -- see
    `eval/k1/tests/test_recommissioning_gap.py`): with the baseline at HEAD (the state right
    after a re-commissioning), an uncommitted edit to a component gave `git diff --name-only
    <base>..HEAD` empty and `git diff --name-only <base>` (no `..HEAD`) the file; an entirely
    untracked new component file -- exactly how `porter_stemmer.py` entered this package -- is
    invisible to `git diff` regardless of the `..HEAD` form and is caught here by
    `git status --porcelain` instead.

    Raises `_RecommissioningCheckUnavailable` -- never a bare subprocess exception -- on any
    failure, so the caller fails toward "outstanding" rather than toward a silent, unverified
    "clear". This is now the only place that claim is made, and both halves of it (the
    tracked-modification path and the untracked-new-file path) are each proven, not asserted."""
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", commit, "--", *COMMISSIONED_COMPONENT_FILES],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--", *COMMISSIONED_COMPONENT_FILES],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RecommissioningCheckUnavailable(f"git query could not run: {exc}") from exc
    if diff_result.returncode != 0:
        raise _RecommissioningCheckUnavailable(
            f"git diff --name-only {commit} exited {diff_result.returncode}: "
            f"{diff_result.stderr.strip()}"
        )
    if status_result.returncode != 0:
        raise _RecommissioningCheckUnavailable(
            f"git status --porcelain exited {status_result.returncode}: "
            f"{status_result.stderr.strip()}"
        )
    changed = {line.strip() for line in diff_result.stdout.splitlines() if line.strip()}
    for line in status_result.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1 format: "XY PATH" (untracked entries are "?? path"). A renamed entry
        # would read "R  old -> new"; that shape cannot occur here since the pathspec is a
        # fixed file list rather than a directory, but the split is defensive rather than
        # assumed.
        path = line[3:].strip().split(" -> ")[-1].strip()
        if path:
            changed.add(path)
    return sorted(changed)


def _derive_recommissioning_gap() -> Tuple[bool, str]:
    """Computes the component re-commissioning gap from git history rather than from a
    hand-typed claim (TE-53 review, J-1/J-2).

    For every decision id currently backing a commissioned set (the values of
    `COMMISSIONING_DECISIONS`), diffs `COMMISSIONED_COMPONENT_FILES` from that decision's own
    `COMMISSIONED_AT_COMMIT` baseline to the actual current working tree
    (`_component_files_changed_since`, which is working-tree aware -- TE-55 review, K-2) --
    the disposition rule's component sentence, executed rather than paraphrased. A decision id
    with no changed files since its own baseline contributes nothing to the result; grouped by
    decision id, the same shape `commissioned_names_clause` already groups the notice's
    set-name text by, so a set commissioned under a new decision id (J-7's own class) is
    covered by construction, not by a list someone remembers to extend.

    Fails toward outstanding rather than toward silence: a decision id with no
    `COMMISSIONED_AT_COMMIT` entry, or a git query that cannot be answered at all (no git
    binary, this directory not a checkout, or a cited commit unreachable), is folded into the
    result as outstanding, with a note naming the check that could not run -- never as a quiet
    `False` that nothing actually verified. That property now also holds for the one branch
    TE-55 found it did not (K-2): a commissioned component modified, or newly added, in the
    working tree but never committed is no longer invisible to this query.

    D-SLM5844: `COMMISSIONED_AT_COMMIT` is append-only, keyed by decision id. Clearing the gap
    for a decision id never edits that id's existing entry -- it files a fresh decision-log
    entry under a NEW decision id, with its own baseline, and re-points the affected sets in
    `COMMISSIONING_DECISIONS` to it. `active_decision_ids` below is therefore always the
    CURRENTLY-cited decision ids only; a superseded id's stale baseline simply stops being
    read, rather than being overwritten.
    """
    active_decision_ids = sorted(set(COMMISSIONING_DECISIONS.values()))
    problems: List[str] = []
    changes_by_decision: Dict[str, List[str]] = {}
    for decision_id in active_decision_ids:
        baseline = COMMISSIONED_AT_COMMIT.get(decision_id)
        if baseline is None:
            problems.append(
                f"{decision_id} has no COMMISSIONED_AT_COMMIT baseline -- its component "
                f"re-commissioning gap cannot be computed and is treated as outstanding"
            )
            continue
        try:
            changed = _component_files_changed_since(baseline)
        except _RecommissioningCheckUnavailable as exc:
            problems.append(f"{decision_id} (baseline {baseline}): {exc}")
            continue
        if changed:
            changes_by_decision[decision_id] = changed

    if not problems and not changes_by_decision:
        return False, ""

    parts = []
    for decision_id in sorted(changes_by_decision):
        changed = changes_by_decision[decision_id]
        baseline = COMMISSIONED_AT_COMMIT[decision_id]
        parts.append(
            f"since {decision_id}'s own commissioning baseline ({baseline}), "
            f"{', '.join(changed)} changed"
        )
    for problem in problems:
        parts.append(f"UNVERIFIED -- {problem}")

    note = (
        "Component re-commissioning gap, computed from git history (including the working "
        "tree -- TE-55 K-2) rather than asserted: "
        + "; ".join(parts) + ". D-SLM5396/D-SLM5397 (Wizard project records tree) record and "
        "defer the gap this replaces the hand-typed claim about. No reading this instrument "
        "produces from any listed change forward has been re-commissioned against the "
        "changed code. Flip to False for a decision id only by an independent seat re-firing "
        "the affected constructions and filing a fresh decision-log entry under a NEW "
        "decision id -- adding that id's own baseline to COMMISSIONED_AT_COMMIT and "
        "re-pointing the affected sets' entries in COMMISSIONING_DECISIONS to it "
        "(D-SLM5844: COMMISSIONED_AT_COMMIT is append-only; no existing key's value is ever "
        "mutated) -- never by editing this note, this function, or an existing "
        "COMMISSIONED_AT_COMMIT entry."
    )
    return True, note


# Executed at import time (K-8, Observation, TE-55 review): every `import eval.k1` shells out
# to `git` once per commissioned decision id -- measured 0.044s -> 0.128s cold
# (`import eval.k1.gate`). Accepted as-is rather than made lazy: the safe direction is
# preserved (an unavailable git yields UNVERIFIED, never a silent clear), the cost is linear
# in a table that grows slowly, and a lazily-computed property would break the
# `from eval.k1 import RECOMMISSIONING_OUTSTANDING` binding `gate.py` relies on.
RECOMMISSIONING_OUTSTANDING, RECOMMISSIONING_NOTE = _derive_recommissioning_gap()


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
    f"{_commissioning_clauses_by_decision(COMMISSIONED_SETS)}. "
    "See eval.k1.COMMISSIONING_DECISIONS for the "
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
