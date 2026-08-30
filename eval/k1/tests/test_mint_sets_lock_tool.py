"""Tests for ``eval/k1/tools/mint_sets_lock.py`` (TE-40 code review, Finding F-9 (Minor),
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree).

``_fetch_one_set`` always returns ``license=None, license_derived=False`` (the fetch has no
license step; design Section 2.4 routes that to the deriver). Before the fix, ``main()``'s
``existing.update(fresh)`` replaced a whole entry, so a bare re-mint silently blanked every
named set's already-derived license fields -- taking the real gate path's
``check_license_present`` guard from *runs* to *refuses*. This exercises the real ``main()``
entry point against a tmp-path copy of ``LOCK_PATH`` (monkeypatched), with the network fetch
stubbed, so the real carry-forward logic runs and only the network boundary is faked."""
from __future__ import annotations

import json

import eval.k1.tools.mint_sets_lock as mod
from eval.k1.sets_lock import SetLockEntry


def _fresh_entry(license_source_note: str) -> SetLockEntry:
    """What `_fetch_one_set` actually returns: no license step, ever."""
    return SetLockEntry(
        hf_repo="mteb/scifact", revision="freshsha", license=None, license_source=None,
        license_derived=False, corpus_docs=5183, queries_all=1109, queries_test=300,
        qrels_test_rows=339, file_digests={"corpus": "x", "queries": "y", "qrels_test": "z"},
        bm25_k1=0.9, bm25_b=0.4, bm25_params_derived=False, fetch_date="2026-08-30",
    )


def test_a_bare_remint_no_longer_blanks_an_already_derived_license(tmp_path, monkeypatch):
    lock_path = tmp_path / "sets.lock.json"
    existing_payload = {
        "schema_version": 1,
        "sets": {
            "scifact": {
                "hf_repo": "mteb/scifact", "revision": "oldsha", "license": "CC BY 4.0",
                "license_source": "https://example.invalid/license", "license_derived": True,
                "corpus_docs": 5183, "queries_all": 1109, "queries_test": 300,
                "qrels_test_rows": 339,
                "file_digests": {"corpus": "x", "queries": "y", "qrels_test": "z"},
                "bm25_k1": 0.9, "bm25_b": 0.4, "bm25_params_derived": False,
                "fetch_date": "2026-08-25", "qrels_reconciled_dropped": 0,
            },
        },
    }
    lock_path.write_text(json.dumps(existing_payload), encoding="utf-8")
    monkeypatch.setattr(mod, "LOCK_PATH", lock_path)
    monkeypatch.setattr(mod, "mint_sets_lock", lambda names: {"scifact": _fresh_entry("refetch")})
    monkeypatch.setattr("sys.argv", ["mint_sets_lock.py"])

    mod.main()

    written = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = written["sets"]["scifact"]
    assert entry["license"] == "CC BY 4.0", "the already-derived license must survive a bare re-mint"
    assert entry["license_derived"] is True
    assert entry["license_source"] == "https://example.invalid/license"
    # Everything the fetch DOES supply (revision, counts) still refreshes -- this is a
    # carry-forward of the license fields specifically, not a refusal to update the entry.
    assert entry["revision"] == "freshsha"


def test_a_remint_of_a_never_derived_set_carries_forward_the_missing_license_honestly(tmp_path, monkeypatch):
    """A set that has never had a license derived (license_derived already False) is not a
    regression case -- the fresh fetch's None is exactly what was already there."""
    lock_path = tmp_path / "sets.lock.json"
    existing_payload = {
        "schema_version": 1,
        "sets": {
            "scifact": {
                "hf_repo": "mteb/scifact", "revision": "oldsha", "license": None,
                "license_source": None, "license_derived": False,
                "corpus_docs": 5183, "queries_all": 1109, "queries_test": 300,
                "qrels_test_rows": 339,
                "file_digests": {"corpus": "x", "queries": "y", "qrels_test": "z"},
                "bm25_k1": 0.9, "bm25_b": 0.4, "bm25_params_derived": False,
                "fetch_date": "2026-08-25", "qrels_reconciled_dropped": 0,
            },
        },
    }
    lock_path.write_text(json.dumps(existing_payload), encoding="utf-8")
    monkeypatch.setattr(mod, "LOCK_PATH", lock_path)
    monkeypatch.setattr(mod, "mint_sets_lock", lambda names: {"scifact": _fresh_entry("refetch")})
    monkeypatch.setattr("sys.argv", ["mint_sets_lock.py"])

    mod.main()

    written = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = written["sets"]["scifact"]
    assert entry["license"] is None
    assert entry["license_derived"] is False


# --------------------------------------------------------------------------------------
# G-4 (Minor, TE-44 review) -- F-9's carry-forward covered license only; bm25_params_derived
# is the identically-shaped sibling group that was left unprotected.
# --------------------------------------------------------------------------------------


def test_a_bare_remint_no_longer_blanks_already_derived_bm25_parameters(tmp_path, monkeypatch):
    """Mirrors the license test above for the sibling ``*_derived`` group. Before the fix,
    ``_fetch_one_set``'s identically-unsupplied ``bm25_k1=0.9, bm25_b=0.4,
    bm25_params_derived=False`` would silently overwrite a real derived pair -- and unlike a
    blanked license (which flips the gate loudly, refuses -> runs), a blanked BM25 parameter
    is replaced by a plausible non-None default, so the guard that only tests for None stays
    green while the gate quietly scores against BEIR defaults instead of the derived values."""
    lock_path = tmp_path / "sets.lock.json"
    existing_payload = {
        "schema_version": 1,
        "sets": {
            "scifact": {
                "hf_repo": "mteb/scifact", "revision": "oldsha", "license": "CC BY 4.0",
                "license_source": "https://example.invalid/license", "license_derived": True,
                "corpus_docs": 5183, "queries_all": 1109, "queries_test": 300,
                "qrels_test_rows": 339,
                "file_digests": {"corpus": "x", "queries": "y", "qrels_test": "z"},
                "bm25_k1": 1.23, "bm25_b": 0.77, "bm25_params_derived": True,
                "fetch_date": "2026-08-25", "qrels_reconciled_dropped": 0,
            },
        },
    }
    lock_path.write_text(json.dumps(existing_payload), encoding="utf-8")
    monkeypatch.setattr(mod, "LOCK_PATH", lock_path)
    monkeypatch.setattr(mod, "mint_sets_lock", lambda names: {"scifact": _fresh_entry("refetch")})
    monkeypatch.setattr("sys.argv", ["mint_sets_lock.py"])

    mod.main()

    written = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = written["sets"]["scifact"]
    assert entry["bm25_k1"] == 1.23, "the already-derived BM25 k1 must survive a bare re-mint"
    assert entry["bm25_b"] == 0.77
    assert entry["bm25_params_derived"] is True
    # the license group (also already derived) must be unaffected by this group's handling
    assert entry["license"] == "CC BY 4.0"
    assert entry["license_derived"] is True
    # what the fetch DOES supply still refreshes
    assert entry["revision"] == "freshsha"


def test_a_remint_of_never_derived_bm25_parameters_carries_forward_the_default_honestly(tmp_path, monkeypatch):
    """A set whose BM25 parameters have never been independently derived
    (bm25_params_derived already False, carrying only the stated BEIR default) is not a
    regression case."""
    lock_path = tmp_path / "sets.lock.json"
    existing_payload = {
        "schema_version": 1,
        "sets": {
            "scifact": {
                "hf_repo": "mteb/scifact", "revision": "oldsha", "license": None,
                "license_source": None, "license_derived": False,
                "corpus_docs": 5183, "queries_all": 1109, "queries_test": 300,
                "qrels_test_rows": 339,
                "file_digests": {"corpus": "x", "queries": "y", "qrels_test": "z"},
                "bm25_k1": 0.9, "bm25_b": 0.4, "bm25_params_derived": False,
                "fetch_date": "2026-08-25", "qrels_reconciled_dropped": 0,
            },
        },
    }
    lock_path.write_text(json.dumps(existing_payload), encoding="utf-8")
    monkeypatch.setattr(mod, "LOCK_PATH", lock_path)
    monkeypatch.setattr(mod, "mint_sets_lock", lambda names: {"scifact": _fresh_entry("refetch")})
    monkeypatch.setattr("sys.argv", ["mint_sets_lock.py"])

    mod.main()

    written = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = written["sets"]["scifact"]
    assert entry["bm25_params_derived"] is False
    assert entry["bm25_k1"] == 0.9
    assert entry["bm25_b"] == 0.4
