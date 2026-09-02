"""tests/witness_structural_matrix.py -- TE-62 (U0 slice B): C31 (witness
integrity, all four structural clauses), C36's U0 legs (a), (b), (e), and
C38 (the witness sees what the product sees, at the seam the product uses)
-- `Claude/Plans/SuperEmbedder_Plan.md` sec 8 (C31, C36, C38), sec 4.4
("The structural law, which is the one thing that can make a witness
blind").

WHY THIS IS ONE DRIVER, MATCHING `tools/ci/run_configure_matrix.py`'s OWN
SHAPE. C31's four clauses, C36's per-process re-derivation legs, and C38's
"-D on an installed header must move witness_sha" are all properties of a
BUILD -- a witness target, a second configure, a definition on
`CMAKE_CXX_FLAGS` -- not properties a single process can assert about
itself at runtime. This project's own existing convention for exactly this
shape is `tools/ci/run_configure_matrix.py`: one JSON report, one row per
LEG, `{leg, expected, observed, passed}`, nothing asserted without a real
invocation behind it.

WHAT EVERY LEG BELOW NEEDS AND DOES NOT YET HAVE: a `semb_witness` target
(sec 4.4's own witness executable) that TE-63 owns, and W-A's/W-Q's
primitive drivers compiled INTO the `superembedder` library and exposed
through one C ABI verb each (C38's own clause). NEITHER EXISTS YET. Every
leg below is therefore reported FAIL, with the SPECIFIC missing
prerequisite named -- never a fabricated PASS, and never a skip (a skipped
leg reads as "nothing to check," which sec 4 forbids for a check that has
not actually run).

  C31 clauses (4 negative + 1 positive):
    (i)   a witness built from a SECOND CONFIGURE must refuse
          (SEMB_WITNESS_FOREIGN_BUILD)
    (ii)  a witness linking a SEPARATELY COMPILED COPY must refuse
          (SEMB_WITNESS_DETACHED_LINK)
    (iii) a driver calling an `inline` engine primitive from its OWN TU
          (not the library's) must refuse (SEMB_WITNESS_TU_ARITHMETIC)
    (iv)  a build reading any of the five fingerprint fields from ANOTHER
          PROCESS must refuse (SEMB_WITNESS_FOREIGN_READING)
    (v)   the POSITIVE construction (a correctly-built witness) must NOT
          refuse

  C36 U0 legs (sec 8's own row; the rest are named U1's per this seat's
  brief):
    (a)   an engine arithmetic change confined to a non-inline .cpp, this
          library byte-identical -> must refuse
    (b)   our own epilogue edited, superslm.lib standing -> must refuse
    (e)   any reading served from outside the process -> must refuse

  C38:
    a `-D` on the `superembedder` library target selecting an #ifdef-gated
    branch inside an INSTALLED ENGINE HEADER (intmath.h's inline
    primitives) must move witness_sha; the SAME `-D` on the WITNESS
    EXECUTABLE's own target (not the library's) must NOT move it -- the
    exact construction that shows a driver living in the witness's own TU
    (rather than the library's) is silently blind.

USAGE: `python tests/witness_structural_matrix.py` prints the JSON report
and exits 0 only if every leg PASSED (never true today) -- 1 otherwise,
with the count of red legs.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent

RESULTS: List[Dict] = []


def leg(name: str, needs: str) -> Dict:
    """Every leg below needs a prerequisite that does not exist yet at
    U0 -- reported honestly, never faked."""
    result = {"leg": name, "expected": "refuses or passes per its own construction",
              "observed": f"MISSING PREREQUISITE: {needs}", "passed": False}
    RESULTS.append(result)
    return result


def has_target(name: str) -> bool:
    """A best-effort, real check: does anything under src/ or the build
    tree even mention this target/symbol yet? (Not a CMake target query --
    no build tree with a witness target exists to query.)"""
    src = REPO_ROOT / "src"
    if not src.exists():
        return False
    for p in src.rglob("*"):
        if p.is_file() and name in p.name:
            return True
    return False


def main(argv: List[str]) -> int:
    witness_exists = has_target("witness")
    wa_driver_compiled_in_library = False  # C38's own clause -- checked below, real

    # semb_wa_pool_abi_contract.h's own symbol must be DEFINED in the
    # superembedder library (not merely declared) for C38's construction
    # to be buildable at all.
    lib_dir = REPO_ROOT / "src"
    wa_symbol_defined_in_src = any(
        "semb_wa_pool_run" in p.read_text(encoding="utf-8", errors="replace")
        for p in lib_dir.rglob("*.cpp")
    ) if lib_dir.exists() else False

    leg("C31(i) second-configure witness must refuse (SEMB_WITNESS_FOREIGN_BUILD)",
        "no semb_witness target exists to build a second configure of")
    leg("C31(ii) detached-link witness must refuse (SEMB_WITNESS_DETACHED_LINK)",
        "no semb_witness target exists to link a separately-compiled copy into")
    leg("C31(iii) TU-local inline-primitive driver must refuse (SEMB_WITNESS_TU_ARITHMETIC)",
        "no W-A driver TU exists yet to construct the TU-local variant of")
    leg("C31(iv) foreign-process reading must refuse (SEMB_WITNESS_FOREIGN_READING)",
        "no witness process exists to construct a foreign-reading variant of")
    leg("C31(v) a correctly-built witness must NOT refuse (the positive construction)",
        "no correctly-built witness exists yet")

    leg("C36(a) engine arithmetic change confined to a non-inline .cpp must refuse",
        f"{'witness target found' if witness_exists else 'no witness target'}; "
        "no per-process re-derivation exists to compare pre/post-edit witness_sha")
    leg("C36(b) our own epilogue edited, superslm.lib standing, must refuse",
        "no epilogue implementation exists in src/ yet (TE-63 owed)")
    leg("C36(e) any reading served from outside the process must refuse",
        "no witness process exists to construct an out-of-process-reading variant of")

    leg("C38 a -D on an INSTALLED ENGINE HEADER's #ifdef branch, compiled into the LIBRARY, "
        "must move witness_sha",
        "W-A's driver is not yet compiled into the superembedder library "
        f"(semb_wa_pool_run defined in src/: {wa_symbol_defined_in_src})")
    leg("C38 the SAME -D on the WITNESS EXECUTABLE's own TU must NOT move witness_sha "
        "(the construction that shows a TU-local driver is blind)",
        "no witness executable target exists to apply the -D to")

    report = {"results": RESULTS, "total": len(RESULTS),
              "passed": sum(1 for r in RESULTS if r["passed"]),
              "failed": sum(1 for r in RESULTS if not r["passed"])}
    print(json.dumps(report, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
