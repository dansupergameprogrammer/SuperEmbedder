"""Permanent load-time join-integrity pin for component 1 (U-K1 fix round, 2026-08-25,
D-SLM4688).

Finding A (`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md` Section 6, Wizard
project records tree): ArguAna's pinned corpus was missing 5 documents its own qrels
referenced as relevant -- a genuine gap in the upstream corpus distribution itself
(independently confirmed against a second, unrelated mirror of the same data), not a fetch
or join defect in this loader. `guards.validate_qrels_join` already catches this shape at
RUN time (aborting the whole run with ``K1_QRELS_EMPTY`` the moment such a set is loaded for
scoring); this module generalizes that guard to LOAD time, for every locked set, as a
standing pin rather than something only discovered when a real gate run happens to reach the
affected set.

This test loads the real, locally-cached data for all four sets (per
StandardsDocument.md 5.4's real-workload rule -- a mocked corpus cannot exercise the
upstream-versioning defect class Finding A actually was) and is skipped, not mocked, when a
set's cache entry is unavailable in this environment.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from eval.k1.sets_lock import SET_REGISTRY, read_sets_lock, load_set

LOCK_PATH = Path(__file__).resolve().parents[1] / "sets.lock.json"


def _dataset_cache_has(repo_id: str) -> bool:
    hf_home = os.environ.get("HF_HOME", "")
    cache_name = repo_id.replace("/", "___")
    return bool(hf_home) and os.path.isdir(os.path.join(hf_home, "datasets", cache_name))


ALL_SET_NAMES = sorted(SET_REGISTRY.keys())


@pytest.mark.parametrize("set_name", ALL_SET_NAMES)
def test_every_qrels_referenced_doc_id_resolves_in_the_loaded_corpus(set_name):
    """For every locked set: every ``corpus-id`` any qrels row names is present in that
    set's loaded corpus. This is the join-integrity property `guards.validate_qrels_join`
    enforces at run time (Probe B's shape); this test enforces it at load time, directly,
    independent of whether a run ever reaches this set. A set failing this test is exactly
    Finding A's shape and is a build finding (a corpus/qrels pin mismatch), never something
    this test's tolerance is loosened to accept."""
    if not os.environ.get("HF_HOME") or not _dataset_cache_has(SET_REGISTRY[set_name]):
        pytest.skip(f"{set_name}: no local HF cache entry for {SET_REGISTRY[set_name]}")

    lock = read_sets_lock(LOCK_PATH)
    entry = lock[set_name]
    corpus, _queries, qrels_rows = load_set(set_name, entry, allow_missing_license=True)

    corpus_ids = {row["_id"] for row in corpus}
    referenced_ids = {row["corpus-id"] for row in qrels_rows}
    unresolved = referenced_ids - corpus_ids

    assert not unresolved, (
        f"{set_name}: {len(unresolved)} qrels-referenced corpus-id(s) do not resolve in the "
        f"loaded {len(corpus_ids)}-document corpus (after reconciliation): "
        f"{sorted(unresolved)[:10]}"
    )
