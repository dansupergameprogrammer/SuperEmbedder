"""tests/te194_c17_sixth_leg_construction.py -- TE-194 (U1 slice 5), cell 5:
C17's sixth leg, the W-Q composition-drift construction
(`Claude/Plans/SuperEmbedder_Plan.md` sec 8 C17: "A sixth leg is landed in
specification and not yet buildable... D19, D-SLM4737, fold 6: vary
semb_query_encode's own COMPOSITION alone -- the join, the order, the
special-token setting, the truncation ordering -- holding every one of the
five fields' inputs byte-identical, and assert SEMB_FINGERPRINT_MISMATCH");
`Claude/Bach/briefs/te194-slice5-red.md` cell 5: "vary semb_query_encode's
own composition alone... in a scratch build... assert
SEMB_FINGERPRINT_MISMATCH at semb_query_open against a bank the reference
build baked. Four mutants, four reds, quoted; the unmodified build opens...
write it so the population is visible (one mutant per crossing-table
element) for the commissioning seat that comes later."

THE CLAIM: once `semb_query_encode` exists and W-Q wires it into
`witness_sha`, four DISTINCT single-element mutations of the query-side
composition -- each holding every OTHER fingerprint input byte-identical to
a reference build -- each move `witness_sha` and therefore
`encoder_fingerprint`, so a bank baked by the reference build and queried
by the mutant build refuses `SEMB_FINGERPRINT_MISMATCH` at
`semb_query_open`. The unmodified (reference-vs-reference) crossing opens
successfully, which is the must-accept half of the SAME population.

THE POPULATION -- ONE MUTANT PER CROSSING-TABLE ELEMENT (sec 3.3's
entry-point crossing table, `semb_query_encode` row: "Applies
query_prefix_bytes, at whatever join, order, special-token setting and
truncation ordering the implementation chooses"), matching TE-37's own four
composition axes (`Claude/Loki/te37-probe/te37_probe.py`) narrowed to the
ones this leg's own commissioning owes, distinct from the join-leg census
te194_query_test.cpp's own MutationProveComposeQueryText already exercises
against THIS FILE's oracle rather than against a scratch product build:

  1. JOIN      -- insert an extra separator byte (e.g. a space or newline)
                  between the compiled-in prefix literal and the caller's
                  text, where the reference build concatenates directly.
  2. ORDER     -- append the prefix after the caller's text instead of
                  prepending it before.
  3. SPECIAL TOKEN -- omit the appended end-of-text token the composed
                  sequence would otherwise carry (or, symmetrically, apply
                  it to the RAW caller text before the prefix join instead
                  of to the composed whole).
  4. TRUNCATION ORDERING -- cut the caller's text to a token budget BEFORE
                  the prefix is joined, where the reference build composes
                  the full string first and cuts the composed result.

RED-UNIMPLEMENTED, BY DESIGN, AT THIS BRANCH'S OWN TIP (21b1735) -- AND
LIKELY BEYOND SLICE 5's OWN BUILD TOO. `semb_query_encode` does not exist
in `src/superembedder/` at all yet (confirmed: `git grep -n
"semb_query_encode" src/` returns nothing), so there is no translation unit
this script can locate and mutate. Its own eventual home is UNDETERMINED --
this script's own best-guess candidate is `src/superembedder/query.cpp`,
matching this project's own established convention (`semb_bank_open`/
`semb_bank_close` live in `bank.cpp`; TE-163's own casebook), but that name
is a GUESS, not a grounded fact, and is stated as a ROUTED FINDING for the
builder to confirm or correct rather than asserted. Whatever the file's own
name turns out to be, this leg's own COMMISSIONING is the residual this
round's dispatch names explicitly ("W-Q's commissioning is not yours and
not the builder's... a seat independent of both authors the pair later") --
so even once the file exists and this script's own scratch-mutate-rebuild
machinery below can run, its readings stay QUARANTINED (StandardsDocument.md
sec 5.4: "an instrument is commissioned before its verdicts are load-bearing
-- and never by its own maker") until that independent seat's own
must-accept/must-reject pair fires. Registered as instrument
TE-194-c17-wq-sixth-leg in `Claude/Instruments/instrument-registry.json`
(this round's own casebook, "Instrument registered").

Exit codes: ALWAYS 0 for a scan that completes, whatever it finds -- an
uncommissioned instrument's reading must never gate the build (the same
discipline tests/c41_part4_object_code_scan.py already states for itself).
A scan that cannot even locate the candidate file prints RED-UNIMPLEMENTED
per mutant and still exits 0 -- that is the correct red-first reading, not
an infrastructure failure, exactly as tests/te163_c34_manifest_honesty_check.py's
own header comment states for the identical shape ("a mutation proof
against a mechanism that does not exist would prove nothing").
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The best-guess candidate TU. A routed finding, not a grounded fact -- see
# this file's own header comment.
CANDIDATE_QUERY_TU_CANDIDATES = [
    "src/superembedder/query.cpp",
]

MUTANTS = [
    ("JOIN", "insert an extra separator byte between the compiled-in prefix literal and the caller's text"),
    ("ORDER", "append the prefix after the caller's text instead of prepending it"),
    ("SPECIAL_TOKEN", "omit the composed sequence's appended end-of-text token, or apply it to the raw "
                       "caller text before the prefix join instead of to the composed whole"),
    ("TRUNCATION_ORDERING", "cut the caller's text to the token budget BEFORE the prefix join, instead of "
                             "composing first and cutting the composed result"),
]


def find_query_tu() -> "Path | None":
    for candidate in CANDIDATE_QUERY_TU_CANDIDATES:
        p = REPO_ROOT / candidate
        if p.exists():
            return p
    return None


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", default="")
    ap.add_argument("--engine-prefix", default="")
    ap.add_argument("--cmake-executable", default="")
    ap.add_argument("--cxx-compiler", default="")
    ap.parse_args(argv)

    print("C17 sixth leg / W-Q composition-drift construction (QUARANTINED; "
          "instrument TE-194-c17-wq-sixth-leg -- see this round's own casebook, "
          "'Instrument registered'):")

    query_tu = find_query_tu()
    if query_tu is None:
        for name, desc in MUTANTS:
            print(f"[RED-UNIMPLEMENTED] C17-sixth-leg/{name}: no candidate query composition TU found "
                  f"under {', '.join(CANDIDATE_QUERY_TU_CANDIDATES)} -- semb_query_encode does not exist "
                  f"yet at this branch's own tip. Mutant description: {desc}. "
                  "ROUTED FINDING: the file's own name is undetermined; this script's own candidate list "
                  "is a guess (bank.cpp's own naming convention applied to the query verbs), not a "
                  "grounded fact -- the builder's round should confirm or correct it.")
        print("[DISPOSITION] population visible (4 mutants, one per crossing-table element: join, order, "
              "special-token setting, truncation ordering), none executable today. Reading QUARANTINED "
              "per StandardsDocument.md sec 5.4 -- recorded, never acted on, never headlined -- and this "
              "script's own exit code is 0 regardless, matching the discipline "
              "tests/c41_part4_object_code_scan.py already states for an uncommissioned instrument.")
        return 0

    # THIS BRANCH IS NOT REACHED TODAY (query_tu is always None at 21b1735 and,
    # per this file's own header comment, likely for some rounds beyond it --
    # the file's own commissioning is explicitly routed to a LATER, independent
    # seat, not to this round's own builder). It is written so a future round
    # that finds the candidate TU present has a starting point rather than a
    # blank page, not because this round executes it.
    print(f"[OBSERVED] candidate query composition TU found at {query_tu} -- this script's own "
          "scratch-clone/mutate/rebuild machinery is NOT implemented in this round (the file did not "
          "exist when this round authored this script, so there was nothing to build the machinery "
          "against). ROUTED: the seat that finds this TU present owns building the four scratch-build "
          "legs against it, per this file's own header comment's mutant descriptions, and owns "
          "confirming that seat is independent of query.cpp's own author before any reading counts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
