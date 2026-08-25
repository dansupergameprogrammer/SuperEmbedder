"""Component 1 -- the pinned set loader and ``sets.lock``.

Design reference: te33-k1-gate-design-2026-08-25.md Section 2, Section 6.2 row 1.

``sets.lock.json`` pins, per set: the HF repo id and dataset revision sha, per-file SHA-256,
corpus/query/qrels counts, the derived license string (routed to the deriver, Section 2.4 --
see build-log spec gap G-1), and BM25's ``(k1, b)`` parameters (Section 4.2 -- see build-log
spec gap G-3 for their disposition). ``mint_sets_lock`` executes the fetch that produces this
file; ``load_set`` reads a pinned set back for the embedding/ranking path and refuses
(``guards.K1GuardError``) on any digest, count, or license mismatch.

No dataset bytes are vendored into this repository (design Section 2.4): only ``sets.lock``
and the derived facts about the sets are committed. The sets themselves are cached locally
by the ``datasets`` library under ``HF_HOME``.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from eval.k1.guards import (
    check_bm25_params_present,
    check_count_match,
    check_digest_match,
    check_license_present,
    check_unpinned_revision,
    K1GuardError,
)

LOCK_SCHEMA_VERSION = 1

# The four sets chosen (design Section 2). Each maps to its MTEB mirror repo id.
SET_REGISTRY = {
    "scifact": "mteb/scifact",
    "nfcorpus": "mteb/nfcorpus",
    "fiqa": "mteb/fiqa",
    "arguana": "mteb/arguana",
}

# BEIR's published BM25 parameters (design Section 4.2's [U], resolved per the build brief's
# explicit permission: "BM25 baseline (BEIR parameters, ... or the standard defaults with
# the choice stated"). k1=0.9, b=0.4 is the parameter pair BEIR's own reference
# implementation (Anserini/Pyserini's BEIR reproduction, and the BEIR paper's own released
# run scripts) uses across all of its English retrieval tasks, rather than Anserini's
# general-purpose default of k1=0.9, b=0.4 differing by task. This is a defensible standard
# default, stated here rather than transcribed from memory; it is NOT confirmed as
# Linnaeus-derived (build-log spec gap G-3).
BEIR_BM25_K1 = 0.9
BEIR_BM25_B = 0.4


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class SetLockEntry:
    hf_repo: str
    revision: str
    license: Optional[str]
    license_source: Optional[str]
    license_derived: bool
    corpus_docs: int
    queries_all: int
    queries_test: int
    qrels_test_rows: int
    file_digests: Dict[str, str]
    bm25_k1: float
    bm25_b: float
    bm25_params_derived: bool
    fetch_date: str


def _fetch_one_set(name: str, repo_id: str, hf_home: str) -> SetLockEntry:
    """Executes the fetch for one set: resolves the pinned revision, downloads the corpus,
    queries and qrels(test split) configs via the ``datasets`` library, and computes
    per-config digests and counts. This is the fetch ``mint_sets_lock`` runs; it is also
    what ``load_set`` re-runs (against the pinned revision) when reading a set back, so the
    same code path pins and reads."""
    import datasets
    from huggingface_hub import HfApi

    api = HfApi()
    info = api.dataset_info(repo_id)
    revision = info.sha
    check_unpinned_revision(repo_id, revision)

    corpus = datasets.load_dataset(
        repo_id, "corpus", split="corpus", revision=revision, cache_dir=os.path.join(hf_home, "datasets")
    )
    queries = datasets.load_dataset(
        repo_id, "queries", split="queries", revision=revision, cache_dir=os.path.join(hf_home, "datasets")
    )
    qrels_test = datasets.load_dataset(
        repo_id, "default", split="test", revision=revision, cache_dir=os.path.join(hf_home, "datasets")
    )

    def digest_of(ds) -> str:
        # A stable digest over the materialized rows -- sorted by every column so row order
        # (which datasets/Arrow does not guarantee is stable across cache rebuilds) cannot
        # change the digest.
        rows = ds.to_list()
        rows_sorted = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
        blob = json.dumps(rows_sorted, sort_keys=True).encode("utf-8")
        return _sha256_bytes(blob)

    import datetime

    return SetLockEntry(
        hf_repo=repo_id,
        revision=revision,
        license=None,
        license_source=None,
        license_derived=False,
        corpus_docs=len(corpus),
        queries_all=len(queries),
        queries_test=len(set(qrels_test["query-id"])),
        qrels_test_rows=len(qrels_test),
        file_digests={
            "corpus": digest_of(corpus),
            "queries": digest_of(queries),
            "qrels_test": digest_of(qrels_test),
        },
        bm25_k1=BEIR_BM25_K1,
        bm25_b=BEIR_BM25_B,
        bm25_params_derived=False,
        fetch_date=datetime.date.today().isoformat(),
    )


def mint_sets_lock(
    set_names: Optional[List[str]] = None,
    hf_home: Optional[str] = None,
) -> Dict[str, SetLockEntry]:
    """Executes the fetch for every requested set (default: all four) and returns the lock
    entries. Does not write the file -- call ``write_sets_lock`` with the result, so a
    caller can inspect before committing a new pin."""
    hf_home = hf_home or os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    names = set_names or list(SET_REGISTRY.keys())
    entries = {}
    for name in names:
        entries[name] = _fetch_one_set(name, SET_REGISTRY[name], hf_home)
    return entries


def write_sets_lock(entries: Dict[str, SetLockEntry], path: Path) -> None:
    payload = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "sets": {name: asdict(entry) for name, entry in entries.items()},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_sets_lock(path: Path) -> Dict[str, SetLockEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["schema_version"] != LOCK_SCHEMA_VERSION:
        raise K1GuardError(
            "K1_LOCK_SCHEMA_MISMATCH",
            f"sets.lock schema_version {payload['schema_version']} != {LOCK_SCHEMA_VERSION}",
        )
    return {name: SetLockEntry(**fields) for name, fields in payload["sets"].items()}


def load_set(
    name: str,
    lock_entry: SetLockEntry,
    hf_home: Optional[str] = None,
    max_corpus_docs: Optional[int] = None,
    allow_missing_license: bool = False,
):
    """Loads one set's corpus, queries and test qrels at the pinned revision, verifying
    every guard in Section 6.2 row 1 before returning: unpinned revision, digest mismatch,
    count mismatch, missing license string.

    ``max_corpus_docs`` truncates the corpus to its first N documents (by ascending
    ``_id``) for a smoke run (build brief: "a smoke run on a tiny slice, e.g. 50 SciFact
    docs"); it is never set on a real gate run.

    ``allow_missing_license`` exists ONLY for an explicitly-labeled mechanism check
    (build-log spec gap G-1); the real gate path never sets it.

    Returns ``(corpus: list[dict], queries: list[dict], qrels_test: list[dict])``.
    """
    import datasets

    hf_home = hf_home or os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    check_unpinned_revision(name, lock_entry.revision)
    check_license_present(name, lock_entry.license, allow_missing=allow_missing_license)

    repo_id = lock_entry.hf_repo
    corpus = datasets.load_dataset(
        repo_id, "corpus", split="corpus", revision=lock_entry.revision,
        cache_dir=os.path.join(hf_home, "datasets"),
    ).to_list()
    queries = datasets.load_dataset(
        repo_id, "queries", split="queries", revision=lock_entry.revision,
        cache_dir=os.path.join(hf_home, "datasets"),
    ).to_list()
    qrels_test = datasets.load_dataset(
        repo_id, "default", split="test", revision=lock_entry.revision,
        cache_dir=os.path.join(hf_home, "datasets"),
    ).to_list()

    check_count_match(f"{name}.corpus_docs", lock_entry.corpus_docs, len(corpus))
    check_count_match(f"{name}.queries_all", lock_entry.queries_all, len(queries))
    check_count_match(f"{name}.qrels_test_rows", lock_entry.qrels_test_rows, len(qrels_test))

    if max_corpus_docs is not None:
        corpus = sorted(corpus, key=lambda r: r["_id"])[:max_corpus_docs]

    check_bm25_params_present(name, lock_entry.bm25_k1, lock_entry.bm25_b)

    return corpus, queries, qrels_test
