"""The Porter (1980) stemmer, for the standard-analyzer BM25 baseline `bm25_baseline.py`
uses as F2's floor (design `te33-k1-gate-design-2026-08-25.md` Section 4.2, amended by
Section 17.2, TE-49).

Design reference: Section 4.2's exact analyzer specification -- "a Porter (1980) stemmer
applied to every remaining token" -- and Section 6.2 row 6's refusal condition ("an analyzer
other than Section 4.2's").

**Verified against Porter's own published sample outputs before use** (Section 4.2: "The
stemmer is verified 66/66 against Porter's own published sample outputs before use") --
``PORTER_SAMPLE_CASES`` below and ``tests/test_porter_stemmer.py`` pin the 66/66 result. The
implementation and its self-check both originate from the disposable probe
(``Claude/Popper/te48-probe/porter.py``, Wizard project records tree) TE-48's debunk built and
executed to attack F2's unanchored floor; this module is that same algorithm, landed as
production code rather than a probe, with its self-check promoted to a pytest.
"""
from __future__ import annotations

VOWELS = "aeiou"


def _is_cons(w: str, i: int) -> bool:
    c = w[i]
    if c in VOWELS:
        return False
    if c == "y":
        return i == 0 or not _is_cons(w, i - 1)
    return True


def _m(w: str) -> int:
    n = 0
    i = 0
    length = len(w)
    while i < length and _is_cons(w, i):
        i += 1
    while i < length:
        while i < length and not _is_cons(w, i):
            i += 1
        if i >= length:
            return n
        n += 1
        while i < length and _is_cons(w, i):
            i += 1
    return n


def _has_vowel(w: str) -> bool:
    return any(not _is_cons(w, i) for i in range(len(w)))


def _dbl_cons(w: str) -> bool:
    return len(w) >= 2 and w[-1] == w[-2] and _is_cons(w, len(w) - 1)


def _cvc(w: str) -> bool:
    if len(w) < 3:
        return False
    if not (
        _is_cons(w, len(w) - 3)
        and not _is_cons(w, len(w) - 2)
        and _is_cons(w, len(w) - 1)
    ):
        return False
    return w[-1] not in "wxy"


def _repl(w: str, suf: str, rep: str, minm: int) -> str:
    stem_ = w[: len(w) - len(suf)]
    return stem_ + rep if _m(stem_) > minm else w


def stem(w: str) -> str:
    """Porter's (1980) algorithm, steps 1a-5b, exactly as published. Returns the stemmed
    form of one lowercase token."""
    if len(w) <= 2:
        return w
    # 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # 1b
    flag = False
    if w.endswith("eed"):
        if _m(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _has_vowel(w[:-2]):
        w = w[:-2]
        flag = True
    elif w.endswith("ing") and _has_vowel(w[:-3]):
        w = w[:-3]
        flag = True
    if flag:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _dbl_cons(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _m(w) == 1 and _cvc(w):
            w += "e"
    # 1c
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # 2
    s2 = [
        ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
        ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
        ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
        ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
        ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
    ]
    for suf, rep in s2:
        if w.endswith(suf):
            w = _repl(w, suf, rep, 0)
            break
    # 3
    s3 = [
        ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
        ("ical", "ic"), ("ful", ""), ("ness", ""),
    ]
    for suf, rep in s3:
        if w.endswith(suf):
            w = _repl(w, suf, rep, 0)
            break
    # 4
    s4 = [
        "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
        "ent", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
    ]
    for suf in s4:
        if w.endswith(suf):
            stem_ = w[: len(w) - len(suf)]
            if _m(stem_) > 1:
                w = stem_
            break
    else:
        if w.endswith("ion"):
            stem_ = w[:-3]
            if _m(stem_) > 1 and stem_ and stem_[-1] in "st":
                w = stem_
    # 5a
    if w.endswith("e"):
        a = w[:-1]
        if _m(a) > 1 or (_m(a) == 1 and not _cvc(a)):
            w = a
    # 5b
    if _m(w) > 1 and _dbl_cons(w) and w.endswith("l"):
        w = w[:-1]
    return w


# Porter's own published sample input/output pairs (Porter, M.F., 1980, "An algorithm for
# suffix stripping"). The stemmer above must reproduce every one of these 66 exactly before
# it is trusted as F2's analyzer -- see tests/test_porter_stemmer.py.
PORTER_SAMPLE_CASES = {
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress",
    "cats": "cat", "feed": "feed", "agreed": "agre", "plastered": "plaster",
    "bled": "bled", "motoring": "motor", "sing": "sing", "conflated": "conflat",
    "troubled": "troubl", "sized": "size", "hopping": "hop", "tanned": "tan",
    "falling": "fall", "hissing": "hiss", "fizzed": "fizz", "failing": "fail",
    "filing": "file", "happy": "happi", "sky": "sky", "relational": "relat",
    "conditional": "condit", "rational": "ration", "valenci": "valenc",
    "hesitanci": "hesit", "digitizer": "digit", "conformabli": "conform",
    "radicalli": "radic", "differentli": "differ", "vileli": "vile",
    "analogousli": "analog", "vietnamization": "vietnam", "predication": "predic",
    "vietnamize": "vietnam", "formalize": "formal", "electriciti": "electr",
    "electrical": "electr", "hopeful": "hope", "goodness": "good",
    "revival": "reviv", "allowance": "allow", "inference": "infer",
    "airliner": "airlin", "gyroscopic": "gyroscop", "adjustable": "adjust",
    "defensible": "defens", "irritant": "irrit", "replacement": "replac",
    "adjustment": "adjust", "dependent": "depend", "adoption": "adopt",
    "homologou": "homolog", "communism": "commun", "activate": "activ",
    "angulariti": "angular", "homologous": "homolog", "effective": "effect",
    "bowdlerize": "bowdler", "probate": "probat", "rate": "rate",
    "cease": "ceas", "controll": "control", "roll": "roll",
}


def self_check() -> tuple[int, int, list[tuple[str, str, str]]]:
    """Runs ``stem`` over every ``PORTER_SAMPLE_CASES`` entry. Returns
    ``(passed, total, mismatches)`` where ``mismatches`` is
    ``[(word, got, expected), ...]`` for every case that did not reproduce."""
    mismatches = [
        (word, stem(word), expected)
        for word, expected in PORTER_SAMPLE_CASES.items()
        if stem(word) != expected
    ]
    total = len(PORTER_SAMPLE_CASES)
    return total - len(mismatches), total, mismatches
