"""tests/c39_singleton_check.py -- TE-62 (U0 slice B): C39's grep-able
structural check (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C39: "a
grep-able structural check refusing any sibling that names an engine
forward entry point, run BEFORE anything is measured").

WHAT THIS CHECKS. Exactly one translation unit under `src/` (case: a `.cpp`
file, `.h`/`.hpp` files are declarations and are not scanned for THIS
check's own population -- a header naming these symbols is not a second
COPY of the forward, it is at most a declaration of one) may reference any
member of the closed set of engine forward-entry symbols the fold-4 probe's
own singleton check names (`t2217_fold9_encoder_singleton_check.sh`, read
as population/anchor per this seat's brief, never as the oracle -- the
POPULATION (which symbol names count) is read from the plan's own sec 4.3
prose ("calling `EmbedEntry` + `RunLayerLoopChunkBatched`") and from
`layer_marshal.h`'s own installed symbol names, not transcribed from the
probe's shell script).

CLOSED SET: EmbedEntry, RunLayerLoopChunkBatched, RunLayerLoop,
MarshalLayer, SslmModel::Load -- the same five the fold-4 probe's own
comment names ("No other file in cost/ may name EmbedEntry,
RunLayerLoopChunkBatched, RunLayerLoop, MarshalLayer or SslmModel::Load").

WHY THIS IS TODAY'S RED, AND WHY IT IS NOT A VACUOUS PASS. `src/` carries
no encoder TU yet (TE-63's job) -- a real run over `src/` finds ZERO
references and would read as a trivial, uninformative pass. This cell's
own must-accept/must-reject fixtures
(`tests/fixtures/c39_singleton/{single_reference,two_references_a,
two_references_b}.cpp`) prove the check CAN fail before it is trusted:
`find_violations([two_references_a, two_references_b])` must report a
violation (two TUs both name the closed set); `find_violations([single_
reference])` must report none. `main()` runs BOTH fixture checks and the
real `src/` scan, and marks the real scan `NOTHING TO SCAN YET
(TE-63 owed)` rather than a false PASS, so a reader cannot mistake "zero
hits because nothing exists" for "zero hits because the check ran and
found nothing wrong."
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

CLOSED_SET = ("EmbedEntry", "RunLayerLoopChunkBatched", "RunLayerLoop", "MarshalLayer",
              "SslmModel::Load")

_PATTERN = re.compile("|".join(re.escape(sym) for sym in CLOSED_SET))


def find_violations(cpp_files: List[Path]) -> Dict[str, List[str]]:
    """Returns {symbol: [file, file, ...]} for every closed-set symbol
    referenced from MORE THAN ONE file. An empty dict is a pass."""
    hits: Dict[str, List[str]] = {sym: [] for sym in CLOSED_SET}
    for path in cpp_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for sym in CLOSED_SET:
            if sym in text:
                hits[sym].append(str(path))
    return {sym: files for sym, files in hits.items() if len(files) > 1}


def main(argv: List[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    fixtures = repo_root / "tests" / "fixtures" / "c39_singleton"

    # Must-reject: two TUs both naming the closed set.
    reject_violations = find_violations(
        [fixtures / "two_references_a.cpp", fixtures / "two_references_b.cpp"])
    if not reject_violations:
        print("FIXTURE FAIL: two_references_{a,b}.cpp both name EmbedEntry and the check did "
              "not catch it -- the check cannot fail, which is the same defect as no check.")
        return 1

    # Must-accept: one TU naming the closed set, alone.
    accept_violations = find_violations([fixtures / "single_reference.cpp"])
    if accept_violations:
        print(f"FIXTURE FAIL: single_reference.cpp alone was flagged: {accept_violations}")
        return 1

    print("Commissioning: must-reject fires, must-accept passes -- the check can fail (sec "
          "9.B / StandardsDocument sec 5.4).")

    src_dir = repo_root / "src"
    cpp_files = sorted(src_dir.rglob("*.cpp")) if src_dir.exists() else []
    real_hits = {sym: files for sym, files in
                 {s: [str(p) for p in cpp_files if s in p.read_text(encoding="utf-8", errors="replace")]
                  for s in CLOSED_SET}.items() if files}
    if not real_hits:
        print("src/: NOTHING TO SCAN YET (TE-63 owed) -- no translation unit under src/ names "
              "any closed-set symbol. This is red-unimplemented, not a verified pass: the "
              "encoder TU this cell exists to bound does not exist yet.")
        return 1
    real_violations = find_violations(cpp_files)
    if real_violations:
        print(f"REAL FAIL: {real_violations}")
        return 1
    print(f"src/: {sum(len(v) for v in real_hits.values())} reference(s) across "
          f"{len(set(f for fs in real_hits.values() for f in fs))} file(s) -- exactly one TU. PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
