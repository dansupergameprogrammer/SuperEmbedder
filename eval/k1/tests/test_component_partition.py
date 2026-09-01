"""Tests for `eval.k1._partition_gap` (TE-55 review, K-1 (Significant),
`Claude/Poirot/6317e68-te55-k1-instrument-confirmation3.md`).

The class this closes: `COMMISSIONED_COMPONENT_FILES` is a hand-typed enumeration, and a
hand-typed enumeration can only ever be checked against itself. Nothing compared it to the
package's actual files, so a new production module was silently out of the re-commissioning
gap's scope until someone remembered to add it -- exactly how `porter_stemmer.py` (193 lines,
created whole in `b16ac70`) went unseen for two review rounds running, alongside seven other
omitted artifacts.

The remedy is deliberately NOT a longer tuple on its own (a longer list is the same defect with
more entries) -- it is a partition: every file physically present under `eval/k1/` is either a
commissioned component or a documented exclusion, checked by walking the real directory rather
than trusting a remembered list. `_partition_gap` returns the files in neither; an empty result
is the property this ticket's brief calls out as the actual fix.

Per the brief's own instruction, this is validated against the exact population TE-55 found:
the check must FAIL on the pre-fix seven-file tuple, naming the omitted artifacts, before it
PASSES on the fixed one."""
from __future__ import annotations

from pathlib import Path

import eval.k1 as k1
from eval.k1.tests._historical_fixtures import SEVEN_FILE_TUPLE_AT_6317E68 as _SEVEN_FILE_TUPLE_AT_6317E68

# TE-57 review, L-6 (Minor): this used to read "the union of both baseline-scoped diffs," which
# is six files (D-SLM4707's own six, D-SLM5363's own two, and porter_stemmer.py/run_spec.py
# appear in both), not eight. The actual eight is that six-file union PLUS pooling.py and
# self_exclusion.py -- two files that changed at NEITHER baseline (so TE-55's diff-based finding
# never named them) but were still physically present and omitted from the pre-fix seven-file
# tuple, which the partition check catches because it compares against the package's real files
# rather than against either baseline's diff.
_ARTIFACTS_TE55_FOUND_OMITTED = (
    "eval/k1/anchors.json",
    "eval/k1/anchors.py",
    "eval/k1/pooling.py",
    "eval/k1/porter_stemmer.py",
    "eval/k1/run_spec.py",
    "eval/k1/self_exclusion.py",
    "eval/k1/set_roster.py",
    "eval/k1/sets.lock.json",
)


def test_partition_gap_fails_on_the_pre_fix_seven_file_tuple_and_names_every_omitted_artifact():
    """Red: reproduces TE-55's own finding exactly. Every artifact the casebook named as
    omitted must appear in the gap `_partition_gap` reports against the pre-fix tuple --
    proving the check would have caught K-1 had it existed before this round, which is the
    brief's own bar for trusting the fix."""
    gap = k1._partition_gap(component_files=_SEVEN_FILE_TUPLE_AT_6317E68)
    assert gap  # non-empty: real files exist that the pre-fix tuple does not account for
    for artifact in _ARTIFACTS_TE55_FOUND_OMITTED:
        assert artifact in gap, f"{artifact} should have been reported omitted, was not in {gap}"


def test_partition_gap_is_empty_on_the_live_component_tuple():
    """Green: every regular file physically present under eval/k1/ is now accounted for as
    either a commissioned component or a documented exclusion -- the property this ticket's
    brief calls the actual fix, not a longer tuple on its own."""
    assert k1._partition_gap() == []


def test_partition_gap_catches_a_new_file_in_neither_list(tmp_path):
    """The property that makes this check unable to go stale: a file added to the package that
    is in neither the component tuple nor a documented exclusion is caught immediately, on a
    disposable package directory standing in for eval/k1/ -- never requires the file to be
    committed, or even for anyone to run the real suite against the real package tree first."""
    package_dir = tmp_path / "k1"
    package_dir.mkdir()
    (package_dir / "a_real_component.py").write_text("X = 1\n", encoding="utf-8")
    (package_dir / "a_forgotten_new_module.py").write_text("Y = 2\n", encoding="utf-8")
    tests_dir = package_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_something.py").write_text("pass\n", encoding="utf-8")

    gap = k1._partition_gap(
        component_files=("eval/k1/a_real_component.py",),
        package_dir=package_dir,
    )
    # The excluded "tests/" directory and its file are never in the gap; the forgotten module
    # is -- in scope by default, exactly the property the brief asked for.
    assert gap == ["eval/k1/a_forgotten_new_module.py"]


def test_documented_exclusions_are_non_empty_and_disjoint_from_the_component_tuple():
    """A basic sanity check on the two exclusion constants themselves: neither is empty (an
    empty exclusion list would make the partition trivially equivalent to "everything must be
    a component"), and no name appears in both lists (a file cannot be simultaneously a
    documented exclusion and a commissioned component)."""
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_DIRS
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_FILES
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_DIR_SUFFIXES
    component_basenames = {f.rsplit("/", 1)[-1] for f in k1.COMMISSIONED_COMPONENT_FILES}
    assert component_basenames.isdisjoint(k1.COMMISSIONED_COMPONENT_EXCLUDED_FILES)


# ----------------------------------------------------------------------------------------
# TE-57 review, L-1 (Significant): the partition was green only in the worktree it was written
# in. Pointed at the live product checkout's package directory (D:\SuperEmbedder\eval\k1),
# `_partition_gap` reported 33 files, every one under `eval/k1/run1_output/` -- the exclusion
# list named `smoke_output` and `te50_output` but not `run1_output`. The routed fix is a rule
# (a `*_output` suffix convention on the directory's own top-level name), not a fourth entry.
# These cells prove the rule generalizes on disposable, portable fixtures -- never against
# D:\SuperEmbedder's actual absolute path, which is a real, evidence-bearing sibling repository
# on this machine and not a fixture this suite should depend on existing at all, let alone at a
# fixed location. The proof against the real product checkout was executed directly (never
# committed as a test) and is recorded in the fix log.
# ----------------------------------------------------------------------------------------


def test_a_fourth_output_directory_is_excluded_without_editing_the_exclusion_list(tmp_path):
    """The property the suffix rule exists to prove: an output directory this package has never
    produced before -- `brand_new_output/`, invented for this test, named nothing like
    `run1_output` or `smoke_output` beyond sharing the suffix -- is excluded from the partition
    the moment it exists on disk, with zero edits to
    `COMMISSIONED_COMPONENT_EXCLUDED_DIRS` or `COMMISSIONED_COMPONENT_EXCLUDED_DIR_SUFFIXES`.
    This is what makes the convention load-bearing rather than a habit: the NEXT output
    directory this arc produces (it has produced roughly one per ticket) is covered by
    construction."""
    package_dir = tmp_path / "k1"
    package_dir.mkdir()
    (package_dir / "a_real_component.py").write_text("X = 1\n", encoding="utf-8")
    fourth_output_dir = package_dir / "brand_new_output"
    (fourth_output_dir / "nested" / "deep").mkdir(parents=True)
    (fourth_output_dir / "evidence.json").write_text("{}\n", encoding="utf-8")
    (fourth_output_dir / "nested" / "deep" / "run_file.txt").write_text("x\n", encoding="utf-8")

    gap = k1._partition_gap(
        component_files=("eval/k1/a_real_component.py",),
        package_dir=package_dir,
    )
    assert gap == []


def test_the_three_shipped_output_directories_are_excluded_by_the_same_single_rule(tmp_path):
    """Regression proof that removing `smoke_output` and `te50_output` from the hand-typed
    `COMMISSIONED_COMPONENT_EXCLUDED_DIRS` list (TE-57 L-1) did not un-exclude them -- all three
    output directories this package has actually produced (`run1_output`, `smoke_output`,
    `te50_output`) are excluded by the one `*_output` suffix rule, with no directory name typed
    into any exclusion list."""
    package_dir = tmp_path / "k1"
    package_dir.mkdir()
    (package_dir / "a_real_component.py").write_text("X = 1\n", encoding="utf-8")
    for name in ("run1_output", "smoke_output", "te50_output"):
        out_dir = package_dir / name
        out_dir.mkdir()
        (out_dir / "result.json").write_text("{}\n", encoding="utf-8")

    gap = k1._partition_gap(
        component_files=("eval/k1/a_real_component.py",),
        package_dir=package_dir,
    )
    assert gap == []
    assert not any(
        name in k1.COMMISSIONED_COMPONENT_EXCLUDED_DIRS
        for name in ("run1_output", "smoke_output", "te50_output")
    )


def test_the_directory_exclusion_is_anchored_to_the_top_level_component_only(tmp_path):
    """TE-57 review, L-7 (Observation): the prior form matched an excluded name against ANY
    path segment, so a nested directory literally named `tests` two levels deep -- inside a real
    component subpackage, not the package's own top-level `tests/` -- would silently vanish from
    the partition too. Anchored to `parts[0]`, a same-named directory that is NOT the top-level
    one is not exempted: its file is still reported in the gap."""
    package_dir = tmp_path / "k1"
    package_dir.mkdir()
    subpkg = package_dir / "subpkg"
    nested_tests_dir = subpkg / "tests"
    nested_tests_dir.mkdir(parents=True)
    (subpkg / "real_module.py").write_text("X = 1\n", encoding="utf-8")
    (nested_tests_dir / "leftover.py").write_text("Y = 2\n", encoding="utf-8")

    gap = k1._partition_gap(
        component_files=("eval/k1/subpkg/real_module.py",),
        package_dir=package_dir,
    )
    # The top-level "tests" exclusion does not reach a directory that merely happens to share
    # its name two levels down -- the nested file is a real gap, not silently exempted.
    assert gap == ["eval/k1/subpkg/tests/leftover.py"]


# ----------------------------------------------------------------------------------------
# TE-57 review, L-5 (Minor): `_partition_gap` walks the disk and reports files the tuple does
# not account for, but performs no converse check -- a tuple entry naming a file that does not
# exist is silent in both mechanisms (a stale or mistyped path silently narrows the
# re-commissioning gap query and the partition test stays green). This closes it: every entry
# in the LIVE `COMMISSIONED_COMPONENT_FILES` must resolve to a real file on disk.
# ----------------------------------------------------------------------------------------


def test_every_commissioned_component_file_resolves_to_a_real_file_on_disk():
    """The converse of the partition: a phantom or mistyped entry in
    `COMMISSIONED_COMPONENT_FILES` would otherwise silently narrow every git query scoped to
    the tuple (`git diff`/`git status` do not error on an unmatched pathspec) without the
    partition ever noticing, since `_partition_gap` only ever reports disk-not-in-tuple, never
    tuple-not-on-disk."""
    missing = [
        f for f in k1.COMMISSIONED_COMPONENT_FILES
        if not (k1._REPO_ROOT / Path(f)).is_file()
    ]
    assert missing == []


def test_every_commissioned_component_file_resolves_to_a_real_file_on_a_disposable_tree(tmp_path):
    """Reproduces the defect L-5 names, on a disposable fixture rather than by mutating the live
    tuple: a stale or mistyped tuple entry naming a file that does not exist is not reported by
    `_partition_gap` (which only walks disk-to-tuple, never tuple-to-disk) -- so the converse
    check above is genuinely load-bearing, not vacuously true because nothing could fail it."""
    package_dir = tmp_path / "k1"
    package_dir.mkdir()
    (package_dir / "a_real_component.py").write_text("X = 1\n", encoding="utf-8")
    component_files = (
        "eval/k1/a_real_component.py",
        "eval/k1/typo_does_not_exist.py",
    )
    # The partition itself stays green: the phantom entry contributes nothing to the disk walk.
    assert k1._partition_gap(component_files=component_files, package_dir=package_dir) == []
    # The converse check this defect requires does catch it.
    missing = [
        f for f in component_files
        if not (package_dir / Path(f).relative_to("eval/k1")).is_file()
    ]
    assert missing == ["eval/k1/typo_does_not_exist.py"]
