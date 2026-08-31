"""Tests for ``eval/k1/porter_stemmer.py`` -- the Porter (1980) stemmer F2's standard
analyzer uses (design Section 4.2, TE-49 amendment). Design Section 4.2: "The stemmer is
verified 66/66 against Porter's own published sample outputs before use." """
from __future__ import annotations

from eval.k1.porter_stemmer import PORTER_SAMPLE_CASES, self_check, stem


def test_porter_reproduces_every_published_sample():
    passed, total, mismatches = self_check()
    assert mismatches == []
    assert passed == total == 66


def test_porter_sample_count_is_66():
    """The design's own claim ("verified 66/66") is a claim about a specific count; pin the
    count itself so a case silently dropped from the table does not shrink the check without
    the design's own text going stale alongside it."""
    assert len(PORTER_SAMPLE_CASES) == 66


def test_stem_is_deterministic_and_idempotent_on_short_words():
    assert stem("a") == "a"
    assert stem("is") == "is"
    assert stem(stem("caresses")) == stem("caresses")
