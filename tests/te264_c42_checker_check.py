"""U1 Slice 7 step 4 (c): the C42 release checker's negative constructions
(TE-264; `Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7 step 4;
`Claude/Plans/SuperEmbedder_Plan.md` sec 4.1a and sec 8 C42; D-SLM7206).

`tools/check_certified_builds.py` checks a certification package:
  (a) all n(n-1)/2 `pairwiseProofs` entries are present, with equal rowDigest;
  (b) each pair's digests are recomputed from the members' evidence files,
      never taken from the JSON;
  (c) each run's `enginePin` equals the document's `enginePin` and the lock's.

THE INTERFACE THIS TEST PINS (the plan names the checker and its clauses but
not its command line; this is the test author's pin, for the planner to
ratify):
  python tools/check_certified_builds.py --root <package root>
reads `<root>/docs/certified-builds.json`, `<root>/superslm.lock` (lines
`tag=`, `commit=`, `tree=`; `tree` is the engine_tree_sha) and each member's
evidence at `<root>/<pairwiseProofs[].evidence>/<build id>/` (`row-digests.tsv`,
`token-id-digest.txt`, `run.json`), the layout plan sec 4.1a fixes.  It exits
0 when the package is accepted and 1 when it is refused, and names every
refused clause on its own output line beginning `REFUSED C42(a)`,
`REFUSED C42(b)` or `REFUSED C42(c)`.  Run against the repository root it
checks the committed interim package.

CELLS, each on a synthetic four-member package this test writes (plan sec 8
C42's "delete one pair from a 4-member set"); synthetic documents may
commission validation and never become the production set (plan sec 4.1a):
  must-accept   the unedited package -> exit 0, no REFUSED line
  (a)           one pairwiseProofs entry deleted -> exit 1, REFUSED C42(a) only
  (b)           one entry's JSON rowDigest disagrees with its runs' evidence
                files (the evidence unchanged) -> exit 1, REFUSED C42(b) only
  (c)           the document's enginePin bumped without re-running (the runs
                and the lock unchanged) -> exit 1, REFUSED C42(c) only
  committed     the repository's own committed package -> exit 0, no REFUSED
                line (the checker's purpose, applied to the document 1.0 ships)

Each construction breaks exactly one clause, so a refusal naming another
clause, or naming every clause, fails its cell.

Exit codes: 0 every cell PASS; 1 any FAIL.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_certified_builds.py"
EVIDENCE = "docs/certification/interim"
PIN = {"tag": "v1.5.0", "commit": "321be4634e14fa5e541bfb8611f06cd7fbb2ae9a",
       "engine_tree_sha": "acaf4b0f22362868422eb9f370ebee280f6820b2fff55953301d3b9060f094e0"}
MEMBERS = ["syn-msvc-avx2", "syn-clangcl-avx2", "syn-gcc-avx2", "syn-msvc-sse2"]
RUN_ID = "syn-interim-run-1"
DATE = "2026-09-18"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_package(root: Path) -> dict:
    """Writes a consistent synthetic package under `root`; returns the document."""
    rows = "".join(f"doc-{i:03d}\t{sha(f'row {i}'.encode())}\n" for i in range(3)).encode()
    token_digest = sha(b"synthetic token ids")
    for member in MEMBERS:
        d = root / EVIDENCE / member
        d.mkdir(parents=True)
        (d / "row-digests.tsv").write_bytes(rows)
        (d / "token-id-digest.txt").write_bytes((token_digest + "\n").encode())
        run = {"buildId": member, "runId": RUN_ID, "date": DATE, "toolchain": "synthetic",
               "enginePin": dict(PIN), "rowDigest": sha(rows), "tokenIdDigest": token_digest}
        (d / "run.json").write_bytes((json.dumps(run, indent=2) + "\n").encode())
    doc = {
        "schemaVersion": 1,
        "release": "interim (synthetic test package)",
        "enginePin": dict(PIN),
        "builds": [{"id": m, "os": "synthetic", "isa": "x86-64", "objectFormat": "COFF",
                    "toolchain": "synthetic", "cpuTier": "AVX2", "artifact": "synthetic", "host": "synthetic"}
                   for m in MEMBERS],
        "pairwiseProofs": [{"a": a, "b": b, "runId": RUN_ID, "date": DATE, "rowDigest": sha(rows),
                            "tokenIdDigest": token_digest, "evidence": EVIDENCE}
                           for a, b in combinations(MEMBERS, 2)],
    }
    write_doc(root, doc)
    (root / "superslm.lock").write_bytes(
        f"tag={PIN['tag']}\ncommit={PIN['commit']}\ntree={PIN['engine_tree_sha']}\n".encode())
    return doc


def write_doc(root: Path, doc: dict) -> None:
    path = root / "docs" / "certified-builds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=2) + "\n").encode())


def run_checker(root: Path, checker: Path) -> tuple[int | None, set[str], str]:
    if not checker.is_file():
        return None, set(), f"{checker} does not exist"
    proc = subprocess.run([sys.executable, str(checker), "--root", str(root)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    out = proc.stdout + proc.stderr
    clauses = set(re.findall(r"^REFUSED C42\(([abc])\)", out, re.M))
    return proc.returncode, clauses, out[-600:]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch", type=Path, default=None)
    ap.add_argument("--checker", type=Path, default=CHECKER,
                    help="the checker under test (default: tools/check_certified_builds.py)")
    args = ap.parse_args(argv)
    scratch = args.scratch or Path(tempfile.mkdtemp(prefix="te264_c42_"))
    failed = False

    def report(ok: bool, cell: str, detail: str) -> None:
        nonlocal failed
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")
        failed |= not ok

    try:
        def fresh(name: str) -> tuple[Path, dict]:
            root = scratch / name
            shutil.rmtree(root, ignore_errors=True)
            return root, write_package(root)

        root, _ = fresh("accept")
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 0 and not clauses, "must-accept: the unedited synthetic four-member package is accepted",
               f"exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")

        root, doc = fresh("a_pair_deleted")
        edited = copy.deepcopy(doc)
        del edited["pairwiseProofs"][3]
        write_doc(root, edited)
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 1 and clauses == {"a"}, "C42 (a): one of six pairs deleted is refused on (a) alone",
               f"exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")

        root, doc = fresh("b_row_digest_forged")
        edited = copy.deepcopy(doc)
        edited["pairwiseProofs"][2]["rowDigest"] = sha(b"a digest no run produced")
        write_doc(root, edited)
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 1 and clauses == {"b"},
               "C42 (b): a JSON rowDigest that disagrees with its runs' evidence files is refused on (b) alone",
               f"exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")

        root, doc = fresh("c_pin_bumped")
        edited = copy.deepcopy(doc)
        edited["enginePin"] = {"tag": "v1.5.1", "commit": "1" * 40, "engine_tree_sha": "2" * 64}
        write_doc(root, edited)
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 1 and clauses == {"c"},
               "C42 (c): the document's engine pin bumped without re-running is refused on (c) alone",
               f"exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")

        rc, clauses, tail = run_checker(ROOT, args.checker)
        committed = ROOT / "docs" / "certified-builds.json"
        report(rc == 0 and not clauses and committed.is_file(),
               "committed: the repository's own interim certification package is accepted",
               f"document present={committed.is_file()}; exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")
    finally:
        if not args.scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    print(f"\nte264_c42_checker_check: {'FAILED' if failed else 'all cells PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
