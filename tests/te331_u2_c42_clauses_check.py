"""tests/te331_u2_c42_clauses_check.py -- TE-331 (U2-3 red suite): the
presence of C42's extended clauses (b'/e/f/g/h) that U2-3 specifies over
today's three-clause checker (`Claude/Plans/te267-u2-release-plan.md` sec 5
U2-3 items 6, 10, 12).

This file was `te331_u2_c42_r9_r10_check.py`. Its R9 and R10 cells (R9-ABSENT,
R10-ABSENT and both C58 legs; C59 was never authored) moved to 1.x with R8
(D-SLM7711, plan sec 11.1: "TE-331's R8-R10 cells leave the red suite") and
were removed in the U2 cloud build. The C42 clause cell is U2-3's and stays.

GROUNDING, RE-CONFIRMED BY DIRECT READ AT `fca421b`:
`tools/check_certified_builds.py` implements clauses (a), (b) and (c) only:
its own `check()` function returns exactly the three-key dict
`{"a": [...], "b": [...], "c": [...]}` -- no key for (b'), (e), (f), (g) or
(h) exists to populate.

One cell:

  C42-CLAUSES the real, unmodified checker's `check()` dict has exactly the
              three keys {a,b,c} -- (b'), (e), (f), (g), (h) do not exist to
              be exercised. Fails loudly (not silently) if the checker ever
              gains a fourth key without this cell being updated to grade it,
              which is the point: a green run here is itself the signal
              nothing changed.

EXIT CODE CONVENTION (te163_bank_pair_check.py's own): 0 only if every cell
is PASS or MISSING PREREQUISITE; 1 if any cell is FAIL or RED-UNIMPLEMENTED.
C42-CLAUSES is RED-UNIMPLEMENTED today by design, and this script exits 1
until the builder's round adds the clauses and this cell is replaced by
their grading.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_certified_builds", REPO_ROOT / "tools" / "check_certified_builds.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def cell_c42_clauses_absent() -> str:
    mod = load_checker_module()
    root = REPO_ROOT  # the committed interim package is at the repo root itself
    refused = mod.check(root)
    keys = set(refused.keys())
    still_three = keys == {"a", "b", "c"}
    status = "RED-UNIMPLEMENTED" if still_three else "FAIL"
    print(f"[{status}] C42-CLAUSES: check() returns keys {sorted(keys)} "
          f"(clauses (b'), (e), (f), (g), (h) are U2-3's own unbuilt additions over today's three; "
          f"a FAIL here means the checker gained a clause this cell does not yet know how to grade "
          f"-- update the cell, don't silently accept a fourth key)")
    return status


def main() -> int:
    argparse.ArgumentParser().parse_args()
    results = [cell_c42_clauses_absent()]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
