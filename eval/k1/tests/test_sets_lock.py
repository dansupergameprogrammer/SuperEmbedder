"""Tests for component 1 -- sets.lock read/write and the load_set guard chain. These do
not hit the network (they construct SetLockEntry objects directly); the real fetch is
exercised by the executed sets.lock.json committed alongside this module and by the smoke
run (build log)."""
from __future__ import annotations

import json

import pytest

from eval.k1.guards import K1GuardError
from eval.k1.sets_lock import (
    LOCK_SCHEMA_VERSION,
    SetLockEntry,
    read_sets_lock,
    write_sets_lock,
)


def _entry(**overrides) -> SetLockEntry:
    base = dict(
        hf_repo="mteb/scifact",
        revision="deadbeef",
        license="MIT",
        license_source="https://example.invalid/license",
        license_derived=True,
        corpus_docs=5183,
        queries_all=1109,
        queries_test=300,
        qrels_test_rows=339,
        file_digests={"corpus": "x", "queries": "y", "qrels_test": "z"},
        bm25_k1=0.9,
        bm25_b=0.4,
        bm25_params_derived=False,
        fetch_date="2026-08-25",
    )
    base.update(overrides)
    return SetLockEntry(**base)


def test_write_and_read_round_trip(tmp_path):
    entries = {"scifact": _entry()}
    path = tmp_path / "sets.lock.json"
    write_sets_lock(entries, path)
    loaded = read_sets_lock(path)
    assert loaded["scifact"] == entries["scifact"]


def test_read_refuses_schema_mismatch(tmp_path):
    path = tmp_path / "sets.lock.json"
    path.write_text(json.dumps({"schema_version": LOCK_SCHEMA_VERSION + 1, "sets": {}}))
    with pytest.raises(K1GuardError) as exc:
        read_sets_lock(path)
    assert exc.value.code == "K1_LOCK_SCHEMA_MISMATCH"


def test_committed_lock_file_matches_design_table():
    """The committed eval/k1/sets.lock.json is the executed fetch's own output (build log).
    This test pins it against the design's own Section 2.1 table so a future edit to the
    lock file that silently drifts from the design is caught."""
    from pathlib import Path

    lock_path = Path(__file__).resolve().parents[1] / "sets.lock.json"
    entries = read_sets_lock(lock_path)
    expected = {
        "scifact": (5183, 1109, 300, 339),
        "nfcorpus": (3633, 3237, 323, 12334),
        "fiqa": (57638, 6648, 648, 1706),
        "arguana": (8674, 1406, 1406, 1406),
    }
    for name, (corpus, q_all, q_test, qrels_rows) in expected.items():
        e = entries[name]
        assert (e.corpus_docs, e.queries_all, e.queries_test, e.qrels_test_rows) == (
            corpus, q_all, q_test, qrels_rows
        ), name
