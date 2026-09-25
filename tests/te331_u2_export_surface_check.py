"""tests/te331_u2_export_surface_check.py -- TE-331 (U2-1 red suite): the
generated export list, `SEMB_API` markings, and the release-blocking
export-count equality check (`Claude/Plans/te267-u2-release-plan.md` sec 5
U2-1; F41, TE-327).

FOUR CELLS.

  TOOL-ABSENT      `tools/generate_export_list.py` does not exist yet
                   (RED-UNIMPLEMENTED). Its own stated scan rule is
                   ^(?:SEMB_API\\s+)?(semb_status|const char\\*)\\s+
                   (semb_[a-z0-9_]+)\\( -- an optional SEMB_API token ahead
                   of the return type, never the un-prefixed anchor alone
                   (which reads 0 declarations once SEMB_API is applied,
                   silently, per F41).

  SEMB-API-ABSENT  `include/superembedder/semb.h` carries NO `SEMB_API`
                   token today (`git grep -c SEMB_API include/superembedder/
                   semb.h` == 0) -- confirmed by direct read, not assumed.
                   RED-UNIMPLEMENTED: the markings U2-1 requires land in
                   the SAME change as the generated export list (never
                   sequenced separately, per the plan's own text), and
                   neither exists.

  SCAN-RULE-MUTATION-PROOF (gradable TODAY, no product change needed): this
  cell embeds the CORRECTED scan rule and the WRONG (un-prefixed-anchor-
  only) rule the plan's own F41 names as the bug, and runs BOTH against
  two scratch copies of the real, committed semb.h -- one unmarked (as it
  is today) and one with SEMB_API applied to every declaration (a
  scratch-only transformation, never written back to the tree). This is
  Curie's own mutation-proof discipline (`Implement/Curie/Curie.md`,
  "Pin the documented claim"): a scan rule that cannot fail under the wrong
  regex pins nothing.
    - both rules read the SAME 12 verbs from the UNMARKED header (today's
      real state) -- the population this repo actually has right now.
    - the corrected rule reads the IDENTICAL 12 verbs from the MARKED
      header; the wrong (un-prefixed) rule reads 0 from the marked header
      -- reproducing F41's own executed finding
      (`Claude/Vitruvius/te327-probe/output.txt`) against THIS tree's real
      header text, not a copied fixture.

  EXPORT-COUNT-CHECK-ABSENT release-blocking check tool/step does not
  exist: no file under `tools/` or `cmake/` implements "recompute semb.h's
  declared-verb set and diff it against the built library's dynamic/static
  symbol table, refusing SEMB_EXPORT_LIST_MISMATCH by name." Grepped for
  by name; RED-UNIMPLEMENTED.

EXIT CODE CONVENTION (te163's own): 0 only if every cell is PASS; 1 if any
is RED-UNIMPLEMENTED or FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CORRECT_RULE = re.compile(r"^(?:SEMB_API\s+)?(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.MULTILINE)
WRONG_RULE = re.compile(r"^(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.MULTILINE)


def mark_with_semb_api(header_text: str) -> str:
    """Scratch-only transformation (never written to the tree): prefixes every
    declaration this scan would find with a SEMB_API token, simulating F41's
    'SEMB_API is applied' state without touching the committed header."""
    def repl(m: re.Match) -> str:
        return "SEMB_API " + m.group(0)
    return WRONG_RULE.sub(repl, header_text)


def cell_tool_absent() -> str:
    path = REPO_ROOT / "tools" / "generate_export_list.py"
    absent = not path.exists()
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] TOOL-ABSENT: {path} exists={path.exists()}")
    return status


def cell_semb_api_absent() -> str:
    header = (REPO_ROOT / "include" / "superembedder" / "semb.h").read_text(encoding="utf-8")
    count = header.count("SEMB_API")
    absent = count == 0
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] SEMB-API-ABSENT: {count} occurrences of SEMB_API in semb.h (expected 0 at fca421b)")
    return status


def cell_scan_rule_mutation_proof() -> str:
    header = (REPO_ROOT / "include" / "superembedder" / "semb.h").read_text(encoding="utf-8")
    marked = mark_with_semb_api(header)

    unmarked_correct = {m.group(2) for m in CORRECT_RULE.finditer(header)}
    unmarked_wrong = {m.group(2) for m in WRONG_RULE.finditer(header)}
    marked_correct = {m.group(2) for m in CORRECT_RULE.finditer(marked)}
    marked_wrong = {m.group(2) for m in WRONG_RULE.finditer(marked)}

    print(f"  unmarked header: correct rule reads {len(unmarked_correct)}, wrong rule reads {len(unmarked_wrong)}")
    print(f"  SEMB_API-marked (scratch-only) header: correct rule reads {len(marked_correct)}, "
          f"wrong rule reads {len(marked_wrong)}")

    ok = (unmarked_correct == unmarked_wrong and len(unmarked_correct) >= 12 and
          marked_correct == unmarked_correct and len(marked_wrong) == 0)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] SCAN-RULE-MUTATION-PROOF: corrected rule is marking-invariant "
          f"({len(marked_correct)} == {len(unmarked_correct)} == {len(unmarked_wrong)} >= 12); "
          f"the wrong (un-prefixed-anchor) rule reads 0 once SEMB_API is applied "
          f"({len(marked_wrong)} == 0) -- reproducing F41's own executed finding against this "
          f"tree's real header text")
    if unmarked_correct:
        print(f"  verbs (unmarked, correct rule): {sorted(unmarked_correct)}")
    return status


def cell_export_count_check_absent() -> str:
    hits = []
    for root_dir in ("tools", "cmake"):
        d = REPO_ROOT / root_dir
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".cmake"):
                text = p.read_text(encoding="utf-8", errors="replace")
                if "SEMB_EXPORT_LIST_MISMATCH" in text:
                    hits.append(str(p))
    absent = len(hits) == 0
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] EXPORT-COUNT-CHECK-ABSENT: files naming SEMB_EXPORT_LIST_MISMATCH: {hits}")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    results = [
        cell_tool_absent(),
        cell_semb_api_absent(),
        cell_scan_rule_mutation_proof(),
        cell_export_count_check_absent(),
    ]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
