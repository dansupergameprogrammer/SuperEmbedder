"""Component 3 -- ranker + dual scorer.

Design reference: te33-k1-gate-design-2026-08-25.md Section 6.2 row 3, Section 3, Section
4.4, and Section 5 (R1, the independent scorer).

- ``cosine_topk`` ranks a corpus against a set of queries and emits a TREC-format run.
- ``ndcg_at_k_own`` is this instrument's own nDCG@10 implementation (the deciding metric,
  Section 3): standard TREC binary/graded gain, standard log2 discount, per query.
- ``ndcg_at_k_pytrec`` is the independent scorer (R1, Section 5): the same run and qrels,
  scored by ``pytrec_eval`` -- the TREC-standard implementation BEIR and MTEB themselves
  use. Agreement to 1e-6 per set is required; disagreement beyond that isolates a metric
  bug in one implementation from a retrieval result.
- ``recall_at_k`` and ``mrr_at_k`` are non-deciding diagnostics (Section 3): reported, never
  used to compute a gate outcome.
- ``achieved_resolving_power`` computes the run's own 95% CI half-width from its per-query
  score dispersion (StandardsDocument.md 5.4).
- ``executed_chance_level`` scores R uniformly-random rankings per set (Section 4.4) rather
  than assuming chance analytically.

Nothing in this module computes a gate verdict (pass/fail against F1/F2). It reports
readings; their standing (load-bearing or quarantined) is asserted in exactly one place,
``eval.k1.COMMISSIONING_NOTICE`` -- see that module for the instrument's current status.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

import numpy as np

from eval.k1.self_exclusion import SELF_EXCLUSION_NOTE, exclude_self_and_truncate

# --------------------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------------------
#
# Self-exclusion (dropping a candidate whose id equals the ranking query's own id, before
# truncating to k) is implemented once, in ``eval.k1.self_exclusion.exclude_self_and_truncate``
# -- see that module and ``SELF_EXCLUSION_NOTE`` for the convention and its provenance.
# ``cosine_topk`` below calls it rather than filtering inline.


def cosine_topk(
    query_vecs: np.ndarray,
    query_ids: Sequence[str],
    corpus_vecs: np.ndarray,
    corpus_ids: Sequence[str],
    k: int,
) -> Dict[str, List[Tuple[str, float]]]:
    """Ranks ``corpus_vecs`` against every query by cosine similarity. Ties are broken by
    ascending corpus id (design Section 11 dimension 6: "ties in the cosine ranking are
    broken by a deterministic rule (document id), because an unstable tie-break is a
    nondeterminism the digest would catch and nobody would understand").

    **Self-exclusion** is delegated entirely to
    ``eval.k1.self_exclusion.exclude_self_and_truncate`` (see ``SELF_EXCLUSION_NOTE``): the
    full corpus-length ranked order is computed first, handed to that shared function along
    with the query's own id and ``k``, and only its result is returned. ArguAna is the only
    one of the four locked sets where a query's text is also indexed as its own corpus
    document (component 3's original build defect, confirmed against BEIR's own source):
    without the exclusion, cosine similarity of a vector against its byte-identical self is
    1.0, guaranteeing the trivial self-match occupies rank 1 on the large majority of
    queries and depresses the deciding metric, never contributing to its numerator.

    Returns ``{query_id: [(corpus_id, score), ...]}``, length ``min(k, len(corpus_ids))`` on
    any query without a self-id collision in the corpus (one shorter only when the corpus
    itself has fewer than ``k`` non-self documents), descending by score.
    """
    q = query_vecs.astype(np.float64)
    c = corpus_vecs.astype(np.float64)
    q_norm = q / np.clip(np.linalg.norm(q, axis=1, keepdims=True), 1e-12, None)
    c_norm = c / np.clip(np.linalg.norm(c, axis=1, keepdims=True), 1e-12, None)
    sims = q_norm @ c_norm.T  # [n_queries, n_corpus]

    corpus_ids_arr = np.asarray(corpus_ids)
    order_by_id = np.argsort(corpus_ids_arr, kind="stable")  # for deterministic tie-break
    kk = min(k, len(corpus_ids))

    run: Dict[str, List[Tuple[str, float]]] = {}
    for i, qid in enumerate(query_ids):
        row = sims[i]
        # Deterministic tie-break: sort by (-score, corpus_id) so equal scores fall back to
        # ascending id order, independent of the corpus's on-disk order.
        idx_sorted_by_id = order_by_id
        scores_by_id_order = row[idx_sorted_by_id]
        # stable sort on -score preserves the id-ascending order among ties
        secondary = np.argsort(-scores_by_id_order, kind="stable")
        full_ranked_idx = idx_sorted_by_id[secondary]  # entire corpus, descending by score
        full_ranked = [(str(corpus_ids_arr[j]), float(row[j])) for j in full_ranked_idx]
        # Self-exclusion (the shared helper): filter before truncation, so a query with no
        # id-collision in the corpus never has its returned list shortened by this step.
        run[qid] = exclude_self_and_truncate(full_ranked, qid, kk)
    return run


# --------------------------------------------------------------------------------------
# Deciding metric -- this instrument's own nDCG@10
# --------------------------------------------------------------------------------------


def write_trec_run(run: Mapping[str, Sequence[Tuple[str, float]]], path, run_name: str = "u-k1") -> None:
    """Writes ``run`` (as produced by ``cosine_topk`` or ``bm25_baseline.bm25_topk``) to a
    standard TREC run file: ``qid Q0 docid rank score run_name``, one line per (query,
    document) pair, rank 1-based.

    This exists so a commissioning executor can reuse an already-computed ranking file
    (the independent commissioning spec's construction 3.3, must-reject 2: "Take
    construction 3.1's already-computed reference-encoder TREC run file for each of the
    four sets (no re-embedding)") without re-running the embedder.
    """
    lines = []
    for qid, ranked in run.items():
        for rank, (docid, score) in enumerate(ranked, start=1):
            lines.append(f"{qid} Q0 {docid} {rank} {score:.6f} {run_name}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def read_trec_run(path) -> Dict[str, List[Tuple[str, float]]]:
    """Reads a TREC run file back into the ``{qid: [(docid, score), ...]}`` shape every
    scoring function in this module consumes. Rows are grouped by query id and returned in
    file order (already rank-sorted by ``write_trec_run``)."""
    run: Dict[str, List[Tuple[str, float]]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            qid, _q0, docid, _rank, score, _run_name = line.split()
            run.setdefault(qid, []).append((docid, float(score)))
    return run


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k_own(
    qrels_by_query: Mapping[str, Mapping[str, float]],
    run: Mapping[str, Mapping[str, float] | Sequence[Tuple[str, float]]],
    k: int = 10,
) -> Tuple[Dict[str, float], float]:
    """This instrument's own nDCG@k. Standard TREC binary/graded gain (the relevance score
    itself, not 2^rel - 1) and the standard log2(rank+1) discount, matching
    ``pytrec_eval``'s ``ndcg_cut`` convention (design Section 3: "the standard TREC
    binary/graded gain and the standard log2 discount").

    A query with IDCG == 0 (no relevant document judged at all) scores 0.0, matching
    trec_eval's own convention -- this never fires on a query that reached this function via
    the real pipeline, because ``guards.validate_qrels_join`` refuses the run first for any
    query with zero qrels rows; it is reachable directly (as in
    ``tests/test_rank_score.py``) to demonstrate what an unguarded scorer would do.

    Returns ``(per_query_ndcg, mean_ndcg)``.
    """
    per_query: Dict[str, float] = {}
    for qid, rels in qrels_by_query.items():
        ideal_gains = sorted((g for g in rels.values() if g > 0), reverse=True)[:k]
        idcg = _dcg(ideal_gains)
        if idcg == 0.0:
            per_query[qid] = 0.0
            continue
        ranked = run.get(qid, [])
        if isinstance(ranked, dict):
            ranked_items = sorted(ranked.items(), key=lambda kv: -kv[1])[:k]
        else:
            ranked_items = list(ranked)[:k]
        gains = [rels.get(docid, 0.0) for docid, _score in ranked_items]
        dcg = _dcg(gains)
        per_query[qid] = dcg / idcg
    mean_ndcg = float(np.mean(list(per_query.values()))) if per_query else 0.0
    return per_query, mean_ndcg


def recall_at_k(
    qrels_by_query: Mapping[str, Mapping[str, float]],
    run: Mapping[str, Sequence[Tuple[str, float]]],
    k: int = 10,
) -> Tuple[Dict[str, float], float]:
    """Non-deciding diagnostic (design Section 3). Fraction of judged-relevant documents
    (score > 0) appearing in the top-k of the run, per query."""
    per_query: Dict[str, float] = {}
    for qid, rels in qrels_by_query.items():
        relevant = {docid for docid, score in rels.items() if score > 0}
        if not relevant:
            per_query[qid] = 0.0
            continue
        ranked_ids = {docid for docid, _s in list(run.get(qid, []))[:k]}
        per_query[qid] = len(relevant & ranked_ids) / len(relevant)
    mean_recall = float(np.mean(list(per_query.values()))) if per_query else 0.0
    return per_query, mean_recall


def mrr_at_k(
    qrels_by_query: Mapping[str, Mapping[str, float]],
    run: Mapping[str, Sequence[Tuple[str, float]]],
    k: int = 10,
) -> Tuple[Dict[str, float], float]:
    """Non-deciding diagnostic (design Section 3). Reciprocal rank of the first relevant
    document in the top-k of the run, per query; 0 if none found in the top-k."""
    per_query: Dict[str, float] = {}
    for qid, rels in qrels_by_query.items():
        relevant = {docid for docid, score in rels.items() if score > 0}
        ranked_ids = [docid for docid, _s in list(run.get(qid, []))[:k]]
        rr = 0.0
        for rank, docid in enumerate(ranked_ids, start=1):
            if docid in relevant:
                rr = 1.0 / rank
                break
        per_query[qid] = rr
    mean_mrr = float(np.mean(list(per_query.values()))) if per_query else 0.0
    return per_query, mean_mrr


# --------------------------------------------------------------------------------------
# R1 -- the independent scorer
# --------------------------------------------------------------------------------------


def ndcg_at_k_pytrec(
    qrels_by_query: Mapping[str, Mapping[str, float]],
    run: Mapping[str, Sequence[Tuple[str, float]]],
    k: int = 10,
) -> Tuple[Dict[str, float], float]:
    """R1 -- the independent scorer. Scores the identical run + qrels with ``pytrec_eval``,
    the TREC-standard scorer BEIR and MTEB themselves use, so a metric implementation bug
    in ``ndcg_at_k_own`` is isolated from a retrieval result (design Section 5, R1).

    Raises ``ImportError`` with a clear message if ``pytrec_eval`` is not installed, per the
    design's stated contingency (Section 5, R1's parenthetical): the independence is the
    requirement, the package is not. A fallback to ``ir_measures`` or a second
    independently-authored nDCG implementation is named there as the contingency; this build
    ships the primary path (``pytrec_eval``, confirmed installable on this Windows/Python
    3.13 toolchain -- see the build log) and the contingency is filed as a spec gap rather
    than built speculatively.

    **Rank-preserving tie-break (U-K1 fix round, 2026-08-25, D-SLM4689).** ``run``'s order
    already carries this instrument's own deterministic tie-break -- ``cosine_topk`` breaks
    exact cosine-score ties by ascending corpus id (design Section 11 dimension 6). Handing
    ``pytrec_eval`` the raw tied scores loses that order: its ``RelevanceEvaluator`` receives
    a plain ``{docid: score}`` mapping and re-sorts internally with its own (unspecified,
    C-side) tie-break, which does not agree with ours. On a set with any exact score tie in
    the top-k -- confirmed on NFCorpus, whose 3,633-document corpus contains near/exact
    duplicate abstracts -- the two scorers can therefore rank the same top-k *set* of
    documents in a different *order*, and nDCG is order-sensitive: the graded relevance
    document lands at a different rank under each scorer's tie-break, producing a real
    disagreement (measured 5.49e-4 on NFCorpus, ~500x the 1e-6 replication threshold; SciFact
    and FiQA-2018, whose relevance is binary and whose corpora produced no exact score tie in
    this run, agreed to floating-point noise). This is not a gain-formula or truncation
    defect -- both scorers use linear gain and identical top-k truncation -- it is a tie-break
    divergence between two independent sort implementations given the same tied input.

    The fix: replace each item's raw score with a strictly decreasing rank-index score
    (``len(items) - rank``) before handing the run to ``pytrec_eval``. This has no ties by
    construction, so ``pytrec_eval``'s sort reproduces ``run``'s existing order exactly,
    regardless of its internal tie-break convention -- R1 becomes a check of ``ndcg_at_k_own``
    against the identical *ranking* rather than a re-adjudication of ties ``cosine_topk``
    already resolved.
    """
    try:
        import pytrec_eval
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise ImportError(
            "pytrec_eval is required for R1 (the independent scorer) and is not installed. "
            "Design Section 5's contingency (ir_measures, or a second independently-"
            "authored nDCG implementation) is filed as build-log spec gap G-2."
        ) from e

    # pytrec_eval requires integer relevance values (its C extension type-checks this).
    # Every qrels source this instrument uses (design Section 2.1: SciFact/FiQA/ArguAna
    # binary at score 1, NFCorpus graded 0-2) is integer-valued already; this cast is a
    # type coercion, not a rounding of real data.
    qrel = {
        qid: {docid: int(rels[docid]) for docid in rels} for qid, rels in qrels_by_query.items()
    }
    run_dict = {}
    for qid, ranked in run.items():
        items = list(ranked)[:k]
        n = len(items)
        # Rank-preserving synthetic score: strictly decreasing by position, so no two items
        # can tie and pytrec_eval's sort cannot disagree with the order `items` already has.
        run_dict[qid] = {docid: float(n - rank) for rank, (docid, _score) in enumerate(items)}
    evaluator = pytrec_eval.RelevanceEvaluator(qrel, {f"ndcg_cut.{k}"})
    results = evaluator.evaluate(run_dict)
    per_query = {qid: metrics.get(f"ndcg_cut_{k}", 0.0) for qid, metrics in results.items()}
    mean_ndcg = float(np.mean(list(per_query.values()))) if per_query else 0.0
    return per_query, mean_ndcg


# --------------------------------------------------------------------------------------
# Resolving power (StandardsDocument.md 5.4)
# --------------------------------------------------------------------------------------


def achieved_resolving_power(per_query_scores: Mapping[str, float]) -> float:
    """95% CI half-width on the mean, computed from THIS run's own per-query dispersion --
    ``1.96 * sigma / sqrt(n)`` -- rather than the a-priori sigma=0.30 assumption the design
    uses only to justify the set choice (Section 4.4). This is the achieved resolving power
    every verdict is stated against."""
    values = list(per_query_scores.values())
    n = len(values)
    if n < 2:
        return float("nan")
    sigma = float(np.std(values, ddof=1))
    return 1.96 * sigma / math.sqrt(n)


# --------------------------------------------------------------------------------------
# Executed chance level (design Section 4.4)
# --------------------------------------------------------------------------------------


@dataclass
class ChanceResult:
    mean: float
    std: float
    trials: int
    per_trial_set_ndcg: List[float]


def chance_level_resolving_power(chance: "ChanceResult") -> float:
    """The minimum effect size a must-reject construction (design Section 6.4; commissioning
    spec Section 2) compares a single candidate reading against: how far a genuinely
    at-chance candidate's ONE nDCG@10 reading can plausibly land from the executed chance
    mean.

    **Resolved interpretive gap (U-K1 fix round, 2026-08-25, build log for the spec's author
    to ratify).** The commissioning spec states this quantity as "the achieved resolving
    power computed from the run's own R=1,000 chance-permutation dispersion" without writing
    out the formula (`Claude/Mendeleev/u-k1-commissioning-2026-08-25.md` Section 2, Wizard
    project records tree). Two readings exist:

    1. Reapply ``achieved_resolving_power``'s own formula (``1.96 * sigma / sqrt(n)``) to the
       ``trials``-length list of per-trial chance nDCG@10 values, i.e. treat the trial count
       as ``n``. At ``trials=1000`` this yields an RP on the order of 1e-5 -- far tighter than
       the spread of a single trial-level reading, and small enough that no single-run
       candidate, including a genuinely at-chance one, could ever land inside it. Under this
       reading the construction can never report "not distinguishable from chance," which
       contradicts the spec's own framing of that outcome as the required, achievable,
       passing result for a must-reject construction.
    2. Use ``1.96 * chance.std`` directly (this function) -- the width of the natural spread
       of ONE trial-level draw from the executed chance distribution, which is the quantity a
       single candidate reading (itself one un-averaged draw) should be compared against.

    Reading 2 is the only one under which the construction is well-posed at all --
    `StandardsDocument.md` Section 5.4's enumerate-then-count rule (exactly one reading
    survives) -- and is what the independent commissioning execution pass actually used
    (`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md` Section 9, decision
    D-SLM4687's provenance). This function encodes that resolution in code so a future
    commissioning re-run reads it from here rather than re-deriving it from the spec's prose.
    This resolution is filed for the commissioning spec's author to ratify -- it has not been
    promoted to an amendment of `Claude/Mendeleev/u-k1-commissioning-2026-08-25.md` itself.
    """
    return 1.96 * chance.std


def executed_chance_level(
    qrels_by_query: Mapping[str, Mapping[str, float]],
    test_query_ids: Sequence[str],
    corpus_ids: Sequence[str],
    k: int = 10,
    trials: int = 1000,
    seed: int = 0,
) -> ChanceResult:
    """Executes ``trials`` uniformly-random rankings per query and reports the mean and
    dispersion of the resulting set-level nDCG@k -- the real chance level, not the
    analytical approximation in design Section 4.4's table (which exists only to justify
    the set choice before any run). Each trial draws, per query, ``min(k, N)`` corpus ids
    uniformly at random without replacement, exactly what a uniformly random ranking's
    top-k prefix looks like.
    """
    rng = np.random.default_rng(seed)
    n_corpus = len(corpus_ids)
    kk = min(k, n_corpus)

    # Precompute each query's gain-by-corpus-index map and its IDCG once.
    corpus_index = {cid: i for i, cid in enumerate(corpus_ids)}
    gain_by_idx: Dict[str, Dict[int, float]] = {}
    idcg_by_q: Dict[str, float] = {}
    for qid in test_query_ids:
        rels = qrels_by_query.get(qid, {})
        gmap = {corpus_index[docid]: g for docid, g in rels.items() if docid in corpus_index and g > 0}
        gain_by_idx[qid] = gmap
        idcg_by_q[qid] = _dcg(sorted(gmap.values(), reverse=True)[:k])

    per_trial: List[float] = []
    for _ in range(trials):
        trial_scores = []
        for qid in test_query_ids:
            idcg = idcg_by_q[qid]
            if idcg == 0.0:
                trial_scores.append(0.0)
                continue
            draw = rng.choice(n_corpus, size=kk, replace=False)
            gains = [gain_by_idx[qid].get(int(idx), 0.0) for idx in draw]
            trial_scores.append(_dcg(gains) / idcg)
        per_trial.append(float(np.mean(trial_scores)) if trial_scores else 0.0)

    return ChanceResult(
        mean=float(np.mean(per_trial)),
        std=float(np.std(per_trial, ddof=1)) if len(per_trial) > 1 else 0.0,
        trials=trials,
        per_trial_set_ndcg=per_trial,
    )
