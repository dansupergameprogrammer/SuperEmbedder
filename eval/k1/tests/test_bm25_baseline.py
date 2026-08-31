"""Tests for component 6 -- the BM25 baseline."""
from __future__ import annotations

import pytest

from eval.k1.guards import K1GuardError
from eval.k1.bm25_baseline import BM25_ANALYZER, _tokenize, bm25_topk, build_bm25_index


# --------------------------------------------------------------------------------------
# The standard analyzer (design Section 4.2, TE-49 amendment, D-SLM5387): stopword removal
# + Porter stemming, replacing the prior bare [A-Za-z0-9]+ tokenizer.
# --------------------------------------------------------------------------------------


def test_tokenize_removes_stopwords():
    """"the", "of" and "to" are in scikit-learn's ENGLISH_STOP_WORDS; content words survive."""
    tokens = _tokenize("The relevance of documents to the query")
    assert "the" not in tokens
    assert "of" not in tokens
    assert "to" not in tokens


def test_tokenize_stems_surviving_tokens():
    """"documents" and "document" must collapse to the same stemmed token, and "relevance"
    must not survive unstemmed -- Porter's own step 4 strips "-ence"."""
    assert _tokenize("documents") == _tokenize("document")
    assert "relevance" not in _tokenize("relevance")


def test_tokenize_is_the_analyzer_bm25_analyzer_names():
    """BM25_ANALYZER is the packet-facing description of what _tokenize does -- pinned so a
    reader of a result packet's ``bm25_analyzer`` field can trust the string names the code
    that actually ran."""
    assert "stop_words" in BM25_ANALYZER.lower()
    assert "porter" in BM25_ANALYZER.lower()
    assert "1980" in BM25_ANALYZER


def _toy_corpus():
    return [
        {"_id": "d1", "title": "Cats", "text": "Cats are small feline mammals that purr."},
        {"_id": "d2", "title": "Dogs", "text": "Dogs are loyal canine mammals that bark."},
        {"_id": "d3", "title": "Rockets", "text": "Rockets use combustion to reach orbit."},
    ]


def test_bm25_ranks_lexically_relevant_doc_first():
    corpus = _toy_corpus()
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "small feline mammals"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    assert run["q1"][0][0] == "d1"


def test_bm25_refuses_missing_params():
    corpus = _toy_corpus()
    with pytest.raises(K1GuardError) as exc:
        build_bm25_index(corpus, k1=None, b=None, set_name="unit")
    assert exc.value.code == "K1_BM25_PARAMS_MISSING"


def test_bm25_ties_break_by_ascending_corpus_id():
    """Uses "identical" rather than "same" as the repeated term: "same" is in scikit-learn's
    ENGLISH_STOP_WORDS (the standard analyzer's stopword list, design Section 4.2, TE-49
    amendment), and a corpus where every document tokenizes to nothing after stopword
    removal leaves ``BM25Okapi`` with an empty vocabulary."""
    corpus = [
        {"_id": "c", "title": "", "text": "identical identical identical"},
        {"_id": "a", "title": "", "text": "identical identical identical"},
        {"_id": "b", "title": "", "text": "identical identical identical"},
    ]
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "identical"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    assert [docid for docid, _s in run["q1"]] == ["a", "b", "c"]


def test_bm25_topk_excludes_query_own_id_from_the_ranked_list():
    """Pin, U-K1 fix round 2b (class fix for D-SLM4699). BM25's equivalent of
    ``test_cosine_topk_excludes_query_own_id_from_the_ranked_list``: a corpus row exists
    under the query's own id, with text identical to the query's -- BM25's maximum possible
    score for that query, exactly the mechanism that would flood ArguAna's rank 1 under an
    unguarded BM25 baseline. The self-id must be excluded from the returned list, and the
    returned list must stay full-length (k), not shortened by the exclusion."""
    corpus = [
        # the query's own id, byte-identical text -- BM25's maximum possible score for the
        # query below (confirmed by execution: this ranks first among these five rows).
        {"_id": "q1", "title": "", "text": "zebras graze quietly near acacia trees at dawn"},
        {"_id": "d_close", "title": "", "text": "zebras graze near acacia trees during the morning"},
        {"_id": "d_mid", "title": "", "text": "zebras wander across open savanna grassland"},
        {"_id": "d_far", "title": "", "text": "penguins swim through icy antarctic waters"},
        {"_id": "d_unrelated", "title": "", "text": "rockets use combustion to reach orbit"},
    ]
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")
    queries = [{"_id": "q1", "text": "zebras graze quietly near acacia trees at dawn"}]
    run = bm25_topk(bm25, corpus_ids, queries, k=3)
    ranked_ids = [docid for docid, _s in run["q1"]]
    assert "q1" not in ranked_ids  # the self-match is excluded
    assert len(ranked_ids) == 3  # the list is NOT shortened by the exclusion
    assert ranked_ids == ["d_close", "d_mid", "d_far"]  # next-best real candidates, in order


def test_bm25_topk_self_exclusion_is_a_no_op_when_no_id_overlaps():
    """The other half of the same pin: a query id that never appears in the corpus (the
    SciFact/NFCorpus/FiQA-2018 shape) must rank byte-identically with the exclusion logic
    present as it would with it absent. Compared directly against the pre-fix reference
    implementation, reproduced verbatim from before this fix round so the "no-op on
    no-overlap" claim is an executed comparison, not an assertion about the code."""
    corpus = [
        {"_id": "c0", "title": "", "text": "small feline mammals that purr"},
        {"_id": "c1", "title": "", "text": "loyal canine mammals that bark"},
        {"_id": "c2", "title": "", "text": "rockets use combustion to reach orbit"},
        {"_id": "c3", "title": "", "text": "birds have feathers and can fly"},
        {"_id": "c4", "title": "", "text": "fish live underwater and have gills"},
    ]
    queries = [
        {"_id": "query-a", "text": "small feline mammals"},
        {"_id": "query-b", "text": "canine mammals bark"},
        {"_id": "query-c", "text": "rockets combustion orbit"},
    ]
    bm25, corpus_ids = build_bm25_index(corpus, k1=0.9, b=0.4, set_name="unit")

    with_exclusion = bm25_topk(bm25, corpus_ids, queries, k=3)

    # Pre-fix reference implementation, reproduced verbatim from before this fix round.
    def _pre_fix_bm25_topk(bm25, corpus_ids, queries, k):
        run = {}
        kk = min(k, len(corpus_ids))
        order_by_id = sorted(range(len(corpus_ids)), key=lambda i: corpus_ids[i])
        for row in queries:
            qid = row["_id"]
            tokens = _tokenize(row["text"])
            scores = bm25.get_scores(tokens)
            ranked = sorted(order_by_id, key=lambda i: (-scores[i], corpus_ids[i]))[:kk]
            run[qid] = [(corpus_ids[i], float(scores[i])) for i in ranked]
        return run

    without_exclusion = _pre_fix_bm25_topk(bm25, corpus_ids, queries, k=3)

    assert with_exclusion == without_exclusion  # byte-identical: the feature is a true no-op
