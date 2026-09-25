"""tests/te331_u2_misc_absence_check.py -- TE-331 (U2-3 red suite): three
smaller mechanisms U2-3 specifies that are absent or behave differently
from the plan's own text at `fca421b`
(`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 items 5, 9; sec 5 U2-7
item 3, C54, F19).

  FORCE-TIER-ABSENT     `tools/pin-superslm/pin_superslm.py` has no
                        `--force-tier` argument (item 5). Grepped for by
                        name against the real argparse setup.
  IDENTITY-FILE-ABSENT  `docs/certification-identity.json` and
                        `tools/write_certification_identity.py` (item 9)
                        do not exist. The document today is the
                        whole-digest interim form (`docs/certified-
                        builds.json`), not the split identity file.
  C54-CRLF-CR-STRIPPED  (real artifact leg, --model/--tokenizer required;
                        MISSING PREREQUISITE otherwise) `semb query --stdin`
                        reads stdin in TEXT mode on Windows today
                        (confirmed at source: `src/main.cpp`'s `--stdin`
                        path sets stdin to binary only when `--raw` is
                        also given, never unconditionally; `LoadCorpus`
                        opens with `std::ifstream stream(path)`, no
                        `std::ios::binary`). A query line piped with a
                        trailing CRLF ("hello\\r\\n") is read by the CRT's
                        text-mode translation as "hello" (no CR): its
                        VECTOR_HEX must equal a one-shot query of the
                        CR-free text "hello", and must DIFFER from a
                        one-shot query of "hello\\r" (with the CR kept) --
                        the shape F19/C54 requires ONCE FIXED is the
                        reverse: the CRLF-piped line's vector must equal
                        "hello\\r"'s, not "hello"'s. This cell runs the
                        real CLI (already built) against the real
                        artifact and asserts TODAY's (wrong) equality,
                        which is exactly the red condition C54 exists to
                        invert.

EXIT CODE CONVENTION (te163's own): 0 only if every leg is PASS or MISSING
PREREQUISITE; 1 if any is FAIL or RED-UNIMPLEMENTED.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def cell_force_tier_absent() -> str:
    text = (REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py").read_text(encoding="utf-8")
    absent = "--force-tier" not in text
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] FORCE-TIER-ABSENT: '--force-tier' in pin_superslm.py: {'--force-tier' in text}")
    return status


def cell_identity_file_absent() -> str:
    doc = REPO_ROOT / "docs" / "certification-identity.json"
    tool = REPO_ROOT / "tools" / "write_certification_identity.py"
    absent = not doc.exists() and not tool.exists()
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] IDENTITY-FILE-ABSENT: {doc} exists={doc.exists()}; {tool} exists={tool.exists()}")
    # Confirm today's document is still the whole-digest interim form (the
    # thing item 9 replaces), not silently already split.
    cb = (REPO_ROOT / "docs" / "certified-builds.json").read_text(encoding="utf-8")
    has_enginepin_here = '"enginePin"' in cb
    print(f"  today's docs/certified-builds.json still carries enginePin inline: {has_enginepin_here} "
          f"(expected True -- item 9 moves it out to the identity file)")
    return status


def cell_c54_crlf_stripped(semb_exe: Path, model: str, tokenizer: str, scratch: Path) -> str:
    if not (model and tokenizer):
        print("[MISSING PREREQUISITE] C54-CRLF-CR-STRIPPED: no --model/--tokenizer given")
        return "MISSING PREREQUISITE"
    if not semb_exe.exists():
        print(f"[MISSING PREREQUISITE] C54-CRLF-CR-STRIPPED: {semb_exe} not built")
        return "MISSING PREREQUISITE"

    scratch.mkdir(parents=True, exist_ok=True)
    stem = str(scratch / "te331_c54_bank")
    corpus = scratch / "corpus.jsonl"
    corpus.write_text('{"id": "d0", "text": "one document"}\n', encoding="utf-8")

    rc = subprocess.run([str(semb_exe), "bake", str(corpus), "--out", stem,
                        "--model", model, "--tokenizer", tokenizer], capture_output=True, text=True)
    if rc.returncode != 0:
        print(f"[FAIL] C54 (setup) bake failed: {rc.stdout}\n{rc.stderr}")
        return "FAIL"

    def one_shot(text: str) -> str:
        p = subprocess.run([str(semb_exe), "query", stem, text, "--model", model, "--tokenizer", tokenizer],
                           capture_output=True, text=True)
        for line in p.stdout.splitlines():
            if line.startswith("VECTOR_HEX="):
                return line[len("VECTOR_HEX="):]
        raise RuntimeError(f"no VECTOR_HEX in one-shot query output: {p.stdout}\n{p.stderr}")

    def stdin_session(raw_bytes: bytes) -> str:
        p = subprocess.run([str(semb_exe), "query", "--stdin", stem, "--model", model, "--tokenizer", tokenizer],
                           input=raw_bytes, capture_output=True)
        stdout = p.stdout.decode("utf-8", errors="replace")
        for line in stdout.splitlines():
            if line.startswith("VECTOR_HEX="):
                return line[len("VECTOR_HEX="):]
        raise RuntimeError(f"no VECTOR_HEX in --stdin output: {stdout}\n{p.stderr.decode(errors='replace')}")

    vec_no_cr = one_shot("hello")
    vec_with_cr = one_shot("hello\r")
    vec_stdin_crlf = stdin_session(b"hello\r\n")

    equals_no_cr_today = vec_stdin_crlf == vec_no_cr
    equals_with_cr = vec_stdin_crlf == vec_with_cr
    print(f"  one-shot 'hello' vector:     {vec_no_cr}")
    print(f"  one-shot 'hello\\r' vector:   {vec_with_cr}")
    print(f"  --stdin 'hello\\r\\n' vector: {vec_stdin_crlf}")
    print(f"  today: stdin-CRLF equals CR-free 'hello'? {equals_no_cr_today} "
          f"(expected True TODAY -- text-mode CRT strips the CR)")
    print(f"  target (F19/C54, once fixed): stdin-CRLF must instead equal 'hello\\r' "
          f"(currently {equals_with_cr}, expected False today)")

    confirmed_todays_bug = equals_no_cr_today and not equals_with_cr and vec_no_cr != vec_with_cr
    status = "RED-UNIMPLEMENTED" if confirmed_todays_bug else "FAIL"
    print(f"[{status}] C54-CRLF-CR-STRIPPED: today's text-mode behavior confirmed by real execution "
          f"on the real artifact -- GREEN once F19/C54 lands and this same construction instead "
          f"asserts stdin-CRLF == 'hello\\r'")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semb-exe", type=Path, default=REPO_ROOT / "build" / "msvc" / "semb.exe")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    ap.add_argument("--scratch", type=Path, default=REPO_ROOT / "build" / "_scratch" / "te331_c54")
    args = ap.parse_args()

    results = [
        cell_force_tier_absent(),
        cell_identity_file_absent(),
        cell_c54_crlf_stripped(args.semb_exe, args.model, args.tokenizer, args.scratch),
    ]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
