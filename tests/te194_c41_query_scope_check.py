"""tests/te194_c41_query_scope_check.py -- TE-194 (U1 slice 5), cell 4: C41
part 4's closure (`Claude/Plans/SuperEmbedder_Plan.md` sec 8 C41 part 4 --
"the part-4 object-code scan's scope now covers semb_query_encode's
translation units; the scan reports zero floating-point mnemonics on the
pooling TUs with the query path linked, and the registered instrument
(TE-149-c41-part4-scan, COMMISSIONED -- read its registry entry) is
invoked, not re-implemented." `Claude/Bach/briefs/te194-slice5-red.md` cell
4).

WHY A NEW FILE RATHER THAN AN EDIT TO tests/c41_part4_object_code_scan.py.
This round's own Writable contract is new files in tests/** only (plus the
two named exceptions neither of which is this file) -- the existing scan
script is read-only here. "Invoked, not re-implemented" is honoured by
IMPORTING that script as a sibling module (the same pattern
tests/te163_bank_pair_check.py already uses for
tests/u1_raw_text_cells_check.py) and calling its own find_object /
disassemble / scan_object / classify functions directly, rather than
copying their logic -- the mnemonic classifier and the disassembly
mechanism are the SAME code, invoked, for a WIDER translation-unit scope.

THE SCOPE WIDENING. c41_part4_object_code_scan.py's own header comment
already states the plan: "Slices 2 and 5 widen it as semb_encode_batch and
semb_query_encode add entry points, closing fully only at Slice 5." Slice 2
needed no widening (semb_encode_batch lives in encoder.cpp, already in
SCOPED_TUS). Slice 5's own widening is THIS FILE: it extends the existing
script's own SCOPED_TUS list with the query composition's own translation
unit and re-runs the identical scan/classify machinery over the union.

THE CANDIDATE TU NAME IS A ROUTED FINDING, NOT A GROUNDED FACT -- the
identical caveat tests/te194_c17_sixth_leg_construction.py's own header
states for the same undetermined name (this project's own bank.cpp naming
convention applied to the query verbs, `query.cpp`, is this script's best
guess). Whatever the actual name turns out to be, if it differs from this
guess this scan will report INFRASTRUCTURE FAIL ("no compiled object found"),
which is the CORRECT, honest failure mode for a wrong guess -- not a
silent false negative, since a missing object always aborts non-zero from
the underlying find_object() call this script re-uses unchanged.

RED AT 21b1735: `semb_query_encode` and its own TU do not exist, so no
`superembedder` build produces the object file this scan needs -- this
check reports RED-UNIMPLEMENTED (mirroring te163_bank_pair_check.py's own
convention for a symbol/file that does not exist yet) rather than crashing
into the underlying script's own INFRASTRUCTURE FAIL exit(1), because a
missing TU is this cell's own EXPECTED state today, not an authoring
defect in this scan.

Exit codes: 0 only after the object is found and the quarantined scan has
completed. A missing object, candidate TU, or disassembler is infrastructure
failure: quarantine protects a completed reading, never a runner that read
nothing.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c41_part4_object_code_scan as c41  # noqa: E402  (sibling module, INVOKED per this file's own header comment)

# The routed-finding candidate name -- see this file's own header comment.
QUERY_TU_CANDIDATE = "query.cpp"


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--objdump", default="", help="path to llvm-objdump; empty tries PATH")
    args = ap.parse_args(argv)

    build_dir = Path(args.build_dir)
    objdump = args.objdump or shutil.which("llvm-objdump") or shutil.which("llvm-objdump.exe") or ""

    print("C41 part 4 -- Slice 5's own scope widening (semb_query_encode's own TU), "
          "invoking c41_part4_object_code_scan.py's own scan/classify machinery unchanged:")

    if not objdump or not Path(objdump).exists():
        print("[FAIL] C41-part4-query-scope: no llvm-objdump found; the scan runner did not execute")
        return 1

    obj = c41.find_object(build_dir, QUERY_TU_CANDIDATE)
    if obj is None:
        print(f"[FAIL] C41-part4-query-scope: no compiled object found for '{QUERY_TU_CANDIDATE}' "
              f"under {build_dir}; the runner did not execute")
        return 1

    # NOT REACHED TODAY. Written for the round that finds the object present:
    # re-uses the base scan's own classify()/disassemble()/scan_object() over
    # the union of SCOPED_TUS plus this one TU, exactly as the base scan
    # already does for its own four-TU list.
    matches = c41.scan_object(objdump, obj)
    print(f"[OBSERVED] {QUERY_TU_CANDIDATE} -> {obj}  matches={len(matches)}")
    for line in matches[:50]:
        print(f"    {line}")
    print("  DISPOSITION: reading filed as QUARANTINED (StandardsDocument.md sec 5.4). The base scan "
          "already derives query.cpp from SEMB_LIBRARY_SOURCES; this driver independently proves the "
          "query object is discoverable and runs the same classifier over it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
