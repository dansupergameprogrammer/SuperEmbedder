"""Component 6 -- the BM25 baseline (F2's lexical floor comparison).

Design reference: te33-k1-gate-design-2026-08-25.md Section 4.2, Section 6.2 row 6.

CPU-only. Uses ``rank_bm25``'s ``BM25Okapi`` with BEIR's standard ``(k1, b)`` parameters
(``sets_lock.BEIR_BM25_K1``, ``sets_lock.BEIR_BM25_B`` -- see that module's docstring for
their disposition; the build brief explicitly permits the standard-default resolution used
here). Refuses (``guards.K1GuardError``, ``K1_BM25_PARAMS_MISSING``) if a set's lock entry
carries no ``(k1, b)`` pair.

**Self-exclusion (U-K1 fix round 2b, 2026-08-25, class fix for D-SLM4699).** ``bm25_topk``
carries the same self-match hazard ``rank_score.cosine_topk`` had before fix round 2: a
document's own text scores at least as high against itself under BM25's lexical overlap as
any other candidate can, so an ArguAna query whose own text is also indexed as a corpus
document under the identical id would self-match at or near rank 1 unless excluded. This
module delegates the exclusion to ``eval.k1.self_exclusion.exclude_self_and_truncate`` -- the
same function ``cosine_topk`` calls -- rather than reimplementing the filter inline.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from eval.k1.guards import check_bm25_params_present
from eval.k1.self_exclusion import exclude_self_and_truncate

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def build_bm25_index(corpus: Sequence[dict], k1: float, b: float, set_name: str = ""):
    """``corpus`` is a list of ``{"_id": ..., "title": ..., "text": ...}`` rows (the BEIR
    corpus shape, design Section 2.1). Document text is ``title + " " + text``, matching
    the BEIR convention and the same concatenation the embedding runner uses (Section 6.2
    row 2)."""
    from rank_bm25 import BM25Okapi

    check_bm25_params_present(set_name, k1, b)
    corpus_ids = [row["_id"] for row in corpus]
    tokenized = [
        _tokenize(f"{row.get('title', '')} {row.get('text', '')}".strip()) for row in corpus
    ]
    bm25 = BM25Okapi(tokenized, k1=k1, b=b)
    return bm25, corpus_ids


def bm25_topk(
    bm25, corpus_ids: Sequence[str], queries: Sequence[dict], k: int
) -> Dict[str, List[Tuple[str, float]]]:
    """Ranks the BM25 index against every query. Ties are broken by ascending corpus id,
    matching the dense ranker's tie-break rule (design Section 11 dimension 6) so the two
    legs of the gate are compared under the same convention.

    Self-exclusion is delegated to ``eval.k1.self_exclusion.exclude_self_and_truncate``: the
    full corpus-length ranked order is computed first (its own deterministic tie-break
    already resolved), then handed to the shared helper along with the query's own id and
    ``k`` -- the identical call the dense ranker makes, so the convention lives in one place
    for both."""
    run: Dict[str, List[Tuple[str, float]]] = {}
    kk = min(k, len(corpus_ids))
    order_by_id = sorted(range(len(corpus_ids)), key=lambda i: corpus_ids[i])
    for row in queries:
        qid = row["_id"]
        tokens = _tokenize(row["text"])
        scores = bm25.get_scores(tokens)
        # Deterministic tie-break: sort by (-score, corpus_id) -- the FULL corpus-length
        # order, not yet truncated to kk (truncation happens inside the shared helper, after
        # self-exclusion, so the exclusion is never applied to an already-shortened list).
        full_ranked_order = sorted(order_by_id, key=lambda i: (-scores[i], corpus_ids[i]))
        full_ranked = [(corpus_ids[i], float(scores[i])) for i in full_ranked_order]
        run[qid] = exclude_self_and_truncate(full_ranked, qid, kk)
    return run
