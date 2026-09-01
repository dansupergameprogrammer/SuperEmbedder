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

import eval.k1 as k1

# The seven-file tuple that shipped at 6317e68 -- TE-55's own review target, before K-1's fix.
# Fixed here as a literal list (not `k1.COMMISSIONED_COMPONENT_FILES`) so this test keeps
# reproducing the SAME historical gap regardless of how the live tuple grows.
_SEVEN_FILE_TUPLE_AT_6317E68 = (
    "eval/k1/bm25_baseline.py",
    "eval/k1/embed_runner.py",
    "eval/k1/gate.py",
    "eval/k1/guards.py",
    "eval/k1/rank_score.py",
    "eval/k1/runner.py",
    "eval/k1/sets_lock.py",
)

# The eight artifacts TE-55's review named as omitted by the pre-fix seven-file tuple (six
# against D-SLM4707's baseline, two against D-SLM5363's -- the union of both, since the
# partition check is not baseline-scoped).
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
    component_basenames = {f.rsplit("/", 1)[-1] for f in k1.COMMISSIONED_COMPONENT_FILES}
    assert component_basenames.isdisjoint(k1.COMMISSIONED_COMPONENT_EXCLUDED_FILES)
