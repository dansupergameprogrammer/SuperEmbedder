"""Component 4 -- the zero-qrels guard, and the instrument's other refusal paths.

Design reference: te33-k1-gate-design-2026-08-25.md Section 6.2, row 4, and Section 6.2's
own framing: "TE-12 Section 2.4 demonstrated mechanically that a harness which reports a
number without checking how many sites resolved cannot distinguish 'correctly disabled'
from 'nothing matched', and that both silently produce a flattering result. The public-set
analogue is a qrels join that matches nothing: every query scores 0 or the scorer silently
drops unjudged queries and averages over the handful that joined, producing a clean-looking
number from almost no data."

This module ships in the instrument's first commit, ahead of every other component, per the
build brief: "the zero-qrels guard in the FIRST commit."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Sequence, Set


class K1GuardError(Exception):
    """Raised by a guard refusal. Carries a stable code so a caller (or a test) can assert
    on the guard that fired without parsing prose."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


@dataclass
class QrelsJoinReport:
    """What the guard found, returned on success so the packet can carry it (design
    Section 10.1, "Guards. Every guard that fired, by name, with what it refused" -- and,
    symmetrically, what a passing guard actually checked)."""

    set_name: str
    test_query_count: int
    queries_with_zero_qrels: Sequence[str]
    total_qrels_rows: int
    total_relevant_in_pool: int
    queries_with_zero_relevant_in_pool: Sequence[str]


def validate_qrels_join(
    set_name: str,
    test_query_ids: Sequence[str],
    qrels_by_query: Mapping[str, Mapping[str, float]],
    corpus_ids: Set[str],
) -> QrelsJoinReport:
    """The zero-qrels guard.

    Refuses (raises ``K1GuardError`` code ``K1_QRELS_EMPTY``) when either:

    1. Any test query has no qrels row at all -- a query joining zero qrels rows must abort
       the run, never score as zero (TE-12 Section 2.4's failure mode, transplanted).
    2. Across the whole set, zero qrels rows resolve to a document actually present in the
       corpus pool being ranked -- the join matched nothing, which a naive scorer would
       report as a clean low (or silently-averaged) number rather than as "the join is
       broken."

    Both conditions are checked at the harness's real join code path -- this function takes
    the same ``qrels_by_query`` and ``corpus_ids`` structures the ranker and scorer consume,
    not a hand-built fixture -- so the guard's vitality can be demonstrated by mutating the
    real inputs (see ``eval/k1/tests/test_guards.py``).

    Returns a ``QrelsJoinReport`` on success. Never returns partial success: a mix of some
    queries with qrels and some without does NOT raise (per-query zero-qrels is legitimate
    in some BEIR-style sets only if genuinely no test query is affected); this function is
    strict per Section 6.2's row 4 -- ANY zero-qrels test query aborts the whole run, because
    a partial abort would silently drop exactly the query most likely to expose a join bug.
    """
    if not test_query_ids:
        raise K1GuardError(
            "K1_QRELS_EMPTY",
            f"[{set_name}] the test query list is empty -- nothing to score",
        )

    queries_with_zero_qrels = [
        qid for qid in test_query_ids if not qrels_by_query.get(qid)
    ]
    if queries_with_zero_qrels:
        raise K1GuardError(
            "K1_QRELS_EMPTY",
            f"[{set_name}] {len(queries_with_zero_qrels)} of {len(test_query_ids)} test "
            f"query(ies) have zero qrels rows: {queries_with_zero_qrels[:10]}"
            f"{'...' if len(queries_with_zero_qrels) > 10 else ''}",
            queries=queries_with_zero_qrels,
        )

    total_qrels_rows = 0
    total_relevant_in_pool = 0
    queries_with_zero_relevant_in_pool = []
    for qid in test_query_ids:
        row = qrels_by_query[qid]
        total_qrels_rows += len(row)
        relevant_in_pool = sum(
            1 for docid, score in row.items() if score > 0 and docid in corpus_ids
        )
        total_relevant_in_pool += relevant_in_pool
        if relevant_in_pool == 0:
            queries_with_zero_relevant_in_pool.append(qid)

    if total_relevant_in_pool == 0:
        raise K1GuardError(
            "K1_QRELS_EMPTY",
            f"[{set_name}] {total_qrels_rows} qrels rows exist across "
            f"{len(test_query_ids)} test queries, but ZERO resolve to a document present "
            f"in the corpus pool being ranked -- the qrels/corpus join matched nothing",
            total_qrels_rows=total_qrels_rows,
        )

    return QrelsJoinReport(
        set_name=set_name,
        test_query_count=len(test_query_ids),
        queries_with_zero_qrels=queries_with_zero_qrels,
        total_qrels_rows=total_qrels_rows,
        total_relevant_in_pool=total_relevant_in_pool,
        queries_with_zero_relevant_in_pool=queries_with_zero_relevant_in_pool,
    )


def check_unpinned_revision(model_name: str, revision: str) -> None:
    """Refuses (``K1_MODEL_UNPINNED``) an embedding run whose model revision is not a
    concrete commit sha. Design Section 6.2, row 2's refusal condition."""
    if not revision or revision in ("main", "latest", "HEAD"):
        raise K1GuardError(
            "K1_MODEL_UNPINNED",
            f"model '{model_name}' has no pinned revision (got {revision!r})",
        )


def check_digest_match(path_label: str, expected_sha256: str, actual_sha256: str) -> None:
    """Refuses (``K1_DIGEST_MISMATCH``) when a fetched file's digest does not match
    ``sets.lock``'s pinned value. Design Section 6.2, row 1's refusal condition."""
    if expected_sha256 != actual_sha256:
        raise K1GuardError(
            "K1_DIGEST_MISMATCH",
            f"{path_label}: expected sha256 {expected_sha256}, got {actual_sha256}",
        )


def check_count_match(label: str, expected: int, actual: int) -> None:
    """Refuses (``K1_COUNT_MISMATCH``) when a fetched set's doc/query/qrels count does not
    match ``sets.lock``'s pinned value."""
    if expected != actual:
        raise K1GuardError(
            "K1_COUNT_MISMATCH", f"{label}: expected count {expected}, got {actual}"
        )


def check_license_present(set_name: str, license_string: str | None, allow_missing: bool = False) -> None:
    """Refuses (``K1_LICENSE_MISSING``) a real (non-mechanism-check) run over a set whose
    ``sets.lock`` entry carries no derived license string. Design Section 6.2, row 1's
    refusal condition and Section 2.4: license derivation is routed to the deriver
    (Linnaeus) and is NOT this instrument's to decide.

    ``allow_missing`` exists ONLY for an explicitly-labeled mechanism check (see build log
    spec gap G-1) and is never set by the real gate path (``run_gate`` in ``runner.py``
    refuses to pass it)."""
    if not license_string and not allow_missing:
        raise K1GuardError(
            "K1_LICENSE_MISSING",
            f"[{set_name}] sets.lock carries no derived license string -- routed to the "
            f"deriver (design Section 2.4); this instrument does not guess it",
        )


def check_stale_anchor(anchor_fetch_date: str, pin_date: str) -> None:
    """Refuses (``K1_STALE_ANCHOR``) when ``anchors.json``'s fetch date predates the
    ``sets.lock`` pin date -- design Section 6.2, row 5's refusal condition."""
    if anchor_fetch_date < pin_date:
        raise K1GuardError(
            "K1_STALE_ANCHOR",
            f"anchor fetched {anchor_fetch_date} is older than the set pinned {pin_date}",
        )


def check_bm25_params_present(set_name: str, k1: float | None, b: float | None) -> None:
    """Refuses (``K1_BM25_PARAMS_MISSING``) a BM25 run whose ``sets.lock`` entry carries no
    ``(k1, b)`` pair. Design Section 6.2, row 6's refusal condition."""
    if k1 is None or b is None:
        raise K1GuardError(
            "K1_BM25_PARAMS_MISSING",
            f"[{set_name}] sets.lock carries no BM25 (k1, b) pair",
        )
