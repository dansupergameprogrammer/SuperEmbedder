"""The self-exclusion convention -- the ONE place it is implemented, for every ranker in
this package.

Design reference: te33-k1-gate-design-2026-08-25.md Section 6.2 row 3 (dense ranker) and row
6 (BM25 baseline). Both rows rank a query against a corpus that can contain the query's own
text as a separately-indexed document under the identical id (ArguAna's shape); scoring a
candidate against its own byte-identical text is that candidate's maximum possible score
under either the dense cosine metric or BM25's lexical overlap, so an unguarded ranker
guarantees the trivial self-match occupies rank 1.

**Provenance (U-K1 fix round 2, 2026-08-25, D-SLM4699).** BEIR's own reference evaluation
harness (``beir/retrieval/evaluation.py::EvaluateRetrieval.evaluate(...,
ignore_identical_ids: bool = True)``) applies this exclusion by default; it is the
convention every published anchor this instrument compares against was itself produced
under.

**Class fix (U-K1 fix round 2b, 2026-08-25, build log for the fix round's date).** Fix round
2 corrected only ``rank_score.cosine_topk``; ``bm25_baseline.bm25_topk`` carried the
identical missing exclusion, unfixed, because each ranker had its own inline copy of the
filter-before-truncate logic. This module extracts that logic into one function so a third
ranker cannot reintroduce the defect by omission -- there is exactly one place the
convention is implemented, and every ranker in this package calls it rather than
reimplementing it.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

SELF_EXCLUSION_NOTE = (
    "Self-exclusion convention: a candidate document whose id equals the ranking query's "
    "own id is dropped from the ranked list before truncation to k (BEIR's "
    "ignore_identical_ids=True, on by default in beir/retrieval/evaluation.py, which is the "
    "convention every published anchor read against this instrument was itself produced "
    "under). This fires only on sets where a query id can also name a corpus document "
    "(ArguAna today); it is a no-op everywhere else, verified by executed check. Implemented "
    "once, in eval.k1.self_exclusion.exclude_self_and_truncate, and applied uniformly by "
    "every ranker in this package (the dense ranker and the BM25 baseline) -- U-K1 fix round "
    "2 (D-SLM4699) fixed the dense ranker; fix round 2b (D-SLM4699 class fix) extracted the "
    "shared helper so the BM25 baseline, which carried the identical defect, is fixed by the "
    "same code rather than a second, independently-written copy."
)


def exclude_self_and_truncate(
    ranked: Sequence[Tuple[str, float]], query_id: str, k: int
) -> List[Tuple[str, float]]:
    """The one self-exclusion implementation in this package. See ``SELF_EXCLUSION_NOTE``.

    ``ranked`` is the FULL corpus-length ranked list for one query -- already in final
    descending-by-score order with that ranker's own deterministic tie-break already
    resolved (ascending corpus id on an exact score tie, design Section 11 dimension 6).
    Every candidate whose id equals ``query_id`` is dropped from that full-length order, and
    only then is the result truncated to ``k``.

    This ordering -- filter, then truncate -- is what makes the exclusion a structural
    no-op on a query with no id collision: the drop happens before the ``k``-slice, so a
    query whose id never appears in ``ranked`` never has its returned list shortened by this
    step. The returned list falls below ``k`` only when the corpus itself, after the drop,
    has fewer than ``k`` candidates left.

    Every ranker in this package MUST call this function rather than reimplementing the
    filter inline -- that is the entire point of extracting it (U-K1 fix round 2b): a third
    ranker that reimplements filter-before-truncate by hand can silently omit it exactly as
    ``bm25_baseline.bm25_topk`` did in fix round 2; a third ranker that calls this function
    cannot.
    """
    return [item for item in ranked if item[0] != query_id][:k]
