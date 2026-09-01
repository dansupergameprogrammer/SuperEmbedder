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
    """A basic sanity check on the three exclusion constants themselves (TE-59 review, M-2
    (Minor) -- this docstring used to say "the two exclusion constants" beside three
    assertions, L-6's own shape reintroduced inside this round's own remedy for L-1): neither
    is empty (an empty exclusion list would make the partition trivially equivalent to
    "everything must be a component"), no name appears in both the component tuple and
    `COMMISSIONED_COMPONENT_EXCLUDED_FILES`, and no component's own top-level path segment
    could be swallowed by `COMMISSIONED_COMPONENT_EXCLUDED_DIRS` or
    `COMMISSIONED_COMPONENT_EXCLUDED_DIR_SUFFIXES` -- currently unreachable (every component is
    a top-level file) and, per M-2's own note, the kind of "currently unreachable" this lineage
    has watched become reachable."""
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_DIRS
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_FILES
    assert k1.COMMISSIONED_COMPONENT_EXCLUDED_DIR_SUFFIXES
    component_basenames = {f.rsplit("/", 1)[-1] for f in k1.COMMISSIONED_COMPONENT_FILES}
    assert component_basenames.isdisjoint(k1.COMMISSIONED_COMPONENT_EXCLUDED_FILES)
    for f in k1.COMMISSIONED_COMPONENT_FILES:
        first_segment = Path(f).relative_to("eval/k1").parts[0]
        assert first_segment not in k1.COMMISSIONED_COMPONENT_EXCLUDED_DIRS
        assert not first_segment.endswith(k1.COMMISSIONED_COMPONENT_EXCLUDED_DIR_SUFFIXES)


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
    tuple-not-on-disk. Calls `k1._phantom_component_entries` -- the same production helper the
    disposable-tree cell below calls (TE-59 review, M-3 (Minor)) -- rather than a comprehension
    local to this test, so the two cells cannot silently diverge again."""
    assert k1._phantom_component_entries() == []


def test_every_commissioned_component_file_resolves_to_a_real_file_on_a_disposable_tree(tmp_path):
    """Reproduces the defect L-5 names, on a disposable fixture rather than by mutating the live
    tuple: a stale or mistyped tuple entry naming a file that does not exist is not reported by
    `_partition_gap` (which only walks disk-to-tuple, never tuple-to-disk). This cell now calls
    the SAME `k1._phantom_component_entries` helper the live cell above calls (TE-59 review,
    M-3 (Minor)) -- previously it recomputed the check itself over a different base expression
    than the live cell used, a paraphrase rather than the check, which stayed green even if the
    live cell's own assertion was deleted or `_REPO_ROOT` was repointed. Calling the shared
    helper from both sites makes that impossible: the converse check is now genuinely
    load-bearing, not vacuously true because nothing could fail it."""
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
    assert k1._phantom_component_entries(
        component_files=component_files, package_dir=package_dir,
    ) == ["eval/k1/typo_does_not_exist.py"]


# ----------------------------------------------------------------------------------------
# TE-59 review, M-1 (Significant): `eval/k1/README.md` stated that which of the tuple and the
# README's "six components" table is normative for "what a component is" was "an open question
# ... has not settled." `D-SLM5863` settled it: the design's own component enumeration is
# normative for what is commissioned, `COMMISSIONED_COMPONENT_FILES` is its file-level
# projection, and the README agrees with the tuple by a cell rather than by prose. These cells
# are that pin.
# ----------------------------------------------------------------------------------------


def test_readme_component_section_agrees_with_the_commissioned_component_tuple():
    """The live cell `D-SLM5863` requires: every file `eval/k1/README.md`'s "The six
    components" section names -- the table plus the `gate.py` / `run_spec.py` / `runner.py`
    prose above it, excluding the two `tools/` CLI wrappers and `eval/k1/__init__.py`, which
    the section itself frames as not components -- must equal `COMMISSIONED_COMPONENT_FILES`
    exactly. A component added to one side and not the other now fails the suite instead of
    drifting silently, which is the failure mode three of today's fifteen entries were already
    exposed to (`gate.py`, `run_spec.py`, `runner.py` are named only in the section's prose,
    never its table)."""
    assert k1._readme_component_files() == set(k1.COMMISSIONED_COMPONENT_FILES)


_FIXTURE_README_TEMPLATE = """# Fixture

## The six components

| # | Component | File |
|---|---|---|
| 1 | Widget | `widget.py` |
| 2 | Gadget | `gadget.py` |

{extra_prose}

## Commissioning status
"""


def test_readme_component_agreement_cell_catches_a_tuple_entry_the_readme_does_not_name(tmp_path):
    """Proof the cell above is not vacuously true (Poirot's own required evidence, TE-59 M-1:
    "the cell is proven by adding a sixteenth entry to `COMMISSIONED_COMPONENT_FILES` in a
    disposable tree and watching the new cell fail"). On a disposable README fixture naming a
    fixed two-file component section, a tuple carrying a THIRD file the README does not name no
    longer compares equal."""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(_FIXTURE_README_TEMPLATE.format(extra_prose=""), encoding="utf-8")
    readme_files = k1._readme_component_files(readme_path=readme_path)
    assert readme_files == {"eval/k1/widget.py", "eval/k1/gadget.py"}
    tuple_with_extra = ("eval/k1/widget.py", "eval/k1/gadget.py", "eval/k1/extra_module.py")
    assert readme_files != set(tuple_with_extra)  # the mutation the cell exists to catch


def test_readme_component_agreement_cell_catches_a_readme_only_mention(tmp_path):
    """The converse direction: a file the README names that the tuple does not carry is also
    caught -- the direction that matters most for a reader, since a stale README entry misleads
    the opposite way from a missing one, and is exactly today's live shape for `gate.py`,
    `run_spec.py` and `runner.py` before this cell existed."""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        _FIXTURE_README_TEMPLATE.format(extra_prose="Also `extra_prose_only.py`."),
        encoding="utf-8",
    )
    readme_files = k1._readme_component_files(readme_path=readme_path)
    tuple_files = {"eval/k1/widget.py", "eval/k1/gadget.py"}
    assert readme_files != tuple_files
    assert "eval/k1/extra_prose_only.py" in readme_files


def test_readme_component_extraction_excludes_the_documented_non_components(tmp_path):
    """The two kinds of documented non-component mention this section frames explicitly -- a
    `tools/` CLI wrapper (named both bare and `tools/`-prefixed, exactly how the real README
    names its two mint wrappers) and `eval/k1/__init__.py` -- are excluded from the extracted
    set, on a disposable fixture reproducing that shape, so the real pin above is not silently
    over-broad."""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# Fixture\n\n"
        "## The six components\n\n"
        "| # | Component | File |\n"
        "|---|---|---|\n"
        "| 1 | Widget | `widget.py` |\n\n"
        "`tools/mint_widget.py` is a CLI wrapper, not a separate component:\n"
        "`mint_widget.py` wraps `widget.py`'s own fetch logic. Not a documented exclusion:\n"
        "(`eval/k1/__init__.py`).\n\n"
        "## Commissioning status\n",
        encoding="utf-8",
    )
    assert k1._readme_component_files(readme_path=readme_path) == {"eval/k1/widget.py"}
