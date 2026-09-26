"""tests/te331_u2_c42_clauses_check.py -- TE-331 (U2-3 red suite): the
set of C42 clauses U2-3 gives the release checker
(`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 items 4, 6, 7, 10, 12, 15).

This file was `te331_u2_c42_r9_r10_check.py`. Its R9 and R10 cells (R9-ABSENT,
R10-ABSENT and both C58 legs; C59 was never authored) moved to 1.x with R8
(D-SLM7711, plan sec 11.1: "TE-331's R8-R10 cells leave the red suite") and
were removed in the U2 cloud build. The C42 clause cell is U2-3's and stays.

THE CONTRACT (U2-3 as built to the plan): `tools/check_certified_builds.py`'s
`check()` returns one refusal list per clause the plan gives the checker, and
exactly those -- ten keys:

  a, b    membership and evidence (plan of record sec 4.1a; kept)
  b'      evidence bound to the cell, the corpus and the run (item 12, P:1223-1237)
  c       the engine pin, read from the identity file from U2-3 on (P:1162-1163)
  c'      freshness over the product's derivation inputs (item 4, P:1055-1060)
  e       the final equality replay (item 6, P:1076-1091)
  f       every certified cell executed at its tier (item 7, P:1096-1106)
  g, h    extension and identity derivation (item 10, P:1160-1168)
  i       a verified GPU's entry is true (item 15, P:1654-1673)

C42 (d), the runtime equality of `certification_epoch`, is not a checker
clause: it is `tests/te264_fingerprint_final_check.py`'s epoch-edit
construction (P:1158-1159), so no `d` key may appear.

One cell:

  C42-CLAUSES the real, unmodified checker's `check()` dict, run on the
              committed package, has exactly those ten keys, each a list.
              A missing key is a clause U2-3 specifies and did not build; an
              extra key is a clause this cell does not know how to grade --
              update the cell, don't silently accept it. The clauses'
              constructions are graded elsewhere (tests/te264_c42_checker_check.py
              and the U2-3 red suite); this cell pins the set.

EXIT CODE CONVENTION (te163_bank_pair_check.py's own): 0 only if every cell
is PASS or MISSING PREREQUISITE; 1 if any cell is FAIL or RED-UNIMPLEMENTED.
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


PLAN_CLAUSES = {"a", "b", "b'", "c", "c'", "e", "f", "g", "h", "i"}


def cell_c42_clauses() -> str:
    mod = load_checker_module()
    root = REPO_ROOT  # the committed package is at the repo root itself
    refused = mod.check(root)
    keys = set(refused.keys())
    lists = all(isinstance(v, list) for v in refused.values())
    missing, extra = sorted(PLAN_CLAUSES - keys), sorted(keys - PLAN_CLAUSES)
    if keys == {"a", "b", "c"}:
        status = "RED-UNIMPLEMENTED"
    else:
        status = "PASS" if keys == PLAN_CLAUSES and lists else "FAIL"
    print(f"[{status}] C42-CLAUSES: check() returns keys {sorted(keys)}; the plan's ten "
          f"{sorted(PLAN_CLAUSES)}; missing={missing} extra={extra} every value a list={lists}")
    return status


def main() -> int:
    argparse.ArgumentParser().parse_args()
    results = [cell_c42_clauses()]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
