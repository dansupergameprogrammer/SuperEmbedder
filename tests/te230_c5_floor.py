"""C5's pre-run, corpus-only class-match@1 calibration.

This file is deliberately executable without `semb`, an artifact, or any build
directory.  It establishes the decision rule before an encoder reading exists:
for a uniformly selected query and uniformly selected *different* candidate
document, chance class-match@1 is sum_c n_c(n_c-1) / (N(N-1)).  C5 requires
twice that corpus-derived chance rate.  All operands are committed corpus
labels or integer literals; no operand is emitted by the artifact C5 grades.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path


# Executed over tests/fixtures/c12b/corpus-239.jsonl: N=239, class counts
# {ood:99, plain:42, multi_slot:28, negation:21, correction:21,
#  underspecified:14, out_of_domain:14}; sum n_c(n_c-1)=13384;
# N(N-1)=56882.  These constants are a pin, not a source for the computation.
EXPECTED_DOCUMENTS = 239
EXPECTED_FAVOURABLE_ORDERED_PAIRS = 13_384
EXPECTED_ORDERED_PAIRS = 56_882
EXPECTED_CHANCE = Fraction(13_384, 56_882)
FLOOR = 2 * EXPECTED_CHANCE


def derive(corpus: Path) -> tuple[int, Counter[str], Fraction]:
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]
    labels = Counter(row["class"] for row in rows)
    n = len(rows)
    if n < 2:
        raise ValueError("C5 requires at least two labelled documents")
    chance = Fraction(sum(count * (count - 1) for count in labels.values()), n * (n - 1))
    return n, labels, chance


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path,
                        default=Path(__file__).resolve().parent / "fixtures" / "c12b" / "corpus-239.jsonl")
    args = parser.parse_args(argv)
    n, labels, chance = derive(args.corpus)
    expected = (n == EXPECTED_DOCUMENTS and
                chance.numerator == EXPECTED_CHANCE.numerator and
                chance.denominator == EXPECTED_CHANCE.denominator and
                n * (n - 1) == EXPECTED_ORDERED_PAIRS and
                sum(v * (v - 1) for v in labels.values()) == EXPECTED_FAVOURABLE_ORDERED_PAIRS)
    print("[{}] C5 calibration: N={} class_counts={} favourable_ordered_pairs={} "
          "ordered_pairs={} chance={}/{} ({:.12f}) floor={}/{} ({:.12f}); "
          "rule=class_match_at_1 >= 2*chance".format(
              "PASS" if expected else "FAIL", n, dict(sorted(labels.items())),
              sum(v * (v - 1) for v in labels.values()), n * (n - 1),
              chance.numerator, chance.denominator, float(chance),
              FLOOR.numerator, FLOOR.denominator, float(FLOOR)))
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
