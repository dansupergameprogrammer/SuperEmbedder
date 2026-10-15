"""tests/te331_u2_misc_absence_check.py -- TE-331 (U2-3 red suite): three
smaller mechanisms U2-3 and U2-7 specify
(`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 items 5, 9; sec 5 U2-7
item 3, C54, F19). The file keeps its name; its two U2-3 cells were absence
cells until U2-3 built both mechanisms, and are now presence checks of the
plan's contract.

  FORCE-TIER            (item 5, P:1061-1062) `tools/pin-superslm/pin_superslm.py`
                        takes `--force-tier {sse2,avx2,avx512}`: driven through
                        the tool's real argument parser, its help lists exactly
                        those three tiers, and an unknown tier (`scalar`, which
                        the plan does not offer) is refused by the parser
                        before any clone, configure or build. The forced pin's
                        own output (its engine-build record's `dispatch` and the
                        macro in its flag record, P:1063-1073) needs an engine
                        build and is not executed here.
  IDENTITY-FILE         (item 9, P:1126-1135) `docs/certification-identity.json`
                        and its only writer `tools/write_certification_identity.py`
                        exist; the file holds exactly `schemaVersion` 1,
                        `product` `superembedder`, `line` 1, `enginePin` {`tag`,
                        `commit`, `engine_tree_sha`} and `proofCorpus` {`path`,
                        `sha256`, `rows`, `corpusDigest`, `tokenIdDigest`} and
                        nothing else; `enginePin` is the tree's `superslm.lock`
                        (`tree=` is `engine_tree_sha`); `proofCorpus.path` is
                        `tests/fixtures/c12b/corpus-239.jsonl`, its `sha256` and
                        `rows` are recomputed here from that file, and its
                        `tokenIdDigest` is `e440e227...`, equal to the interim
                        evidence's `token-id-digest.txt` (P:1135); and the writer's
                        `--check` finds the committed file byte-identical to
                        what it writes from this tree at line 1 (C42 (h)'s rule,
                        P:1161-1162).
  C54-CRLF-CR-KEPT      (real artifact leg, --model/--tokenizer required;
                        MISSING PREREQUISITE otherwise) `semb query --stdin`
                        reads stdin in binary mode (`src/main.cpp` sets it
                        unconditionally), so a CR before the LF is query
                        text, as F19/C54 require. A line piped as
                        "hello\\r\\n" must give the VECTOR_HEX of a one-shot
                        query of "hello\\r" (CR kept) and must differ from
                        a one-shot query of "hello". If those two one-shot
                        references are themselves equal (a synthetic
                        tokenizer can encode them alike), the cell cannot
                        tell the cases apart and reports MISSING
                        PREREQUISITE: only the real artifact grades it.

EXIT CODE CONVENTION (te163's own): 0 only if every leg is PASS or MISSING
PREREQUISITE; 1 if any is FAIL or RED-UNIMPLEMENTED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


PLAN_FORCE_TIERS = ("sse2", "avx2", "avx512")  # P:1061
IDENTITY_KEYS = ["schemaVersion", "product", "line", "enginePin", "proofCorpus"]  # P:1127-1130
ENGINE_PIN_KEYS = {"tag", "commit", "engine_tree_sha"}
PROOF_CORPUS_KEYS = {"path", "sha256", "rows", "corpusDigest", "tokenIdDigest"}
PROOF_CORPUS_PATH = "tests/fixtures/c12b/corpus-239.jsonl"
TOKEN_ID_DIGEST_PREFIX = "e440e227"  # P:1135, [M]


def cell_force_tier() -> str:
    tool = REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"
    helped = subprocess.run([sys.executable, str(tool), "--help"], capture_output=True, text=True, timeout=120)
    m = re.search(r"--force-tier \{([^}]*)\}", helped.stdout)
    offered = tuple(m.group(1).split(",")) if m else None
    bad = subprocess.run([sys.executable, str(tool), "--prefix", str(REPO_ROOT / "build" / "_scratch" / "te331_ft"),
                          "--force-tier", "scalar"], capture_output=True, text=True, timeout=120)
    refused = bad.returncode == 2 and "invalid choice: 'scalar'" in bad.stderr
    ok = helped.returncode == 0 and offered == PLAN_FORCE_TIERS and refused
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] FORCE-TIER: --help exit={helped.returncode} offers {offered} (plan {PLAN_FORCE_TIERS}); "
          f"--force-tier scalar exit={bad.returncode} refused by the parser={refused}: {bad.stderr.strip()[-200:]!r}")
    return status


def cell_identity_file() -> str:
    doc = REPO_ROOT / "docs" / "certification-identity.json"
    tool = REPO_ROOT / "tools" / "write_certification_identity.py"
    problems = []
    if not doc.is_file() or not tool.is_file():
        print(f"[FAIL] IDENTITY-FILE: {doc} exists={doc.exists()}; {tool} exists={tool.exists()}")
        return "FAIL"
    ident = json.loads(doc.read_bytes().decode("ascii"))
    if list(ident) != IDENTITY_KEYS:
        problems.append(f"members {list(ident)} != {IDENTITY_KEYS}")
    if ident.get("schemaVersion") != 1 or ident.get("product") != "superembedder" or ident.get("line") != 1:
        problems.append(f"schemaVersion/product/line = {ident.get('schemaVersion')!r}/{ident.get('product')!r}/"
                        f"{ident.get('line')!r}")
    pin, pc = ident.get("enginePin") or {}, ident.get("proofCorpus") or {}
    if set(pin) != ENGINE_PIN_KEYS:
        problems.append(f"enginePin members {sorted(pin)}")
    if set(pc) != PROOF_CORPUS_KEYS:
        problems.append(f"proofCorpus members {sorted(pc)}")
    lock = dict(l.split("=", 1) for l in (REPO_ROOT / "superslm.lock").read_text(encoding="utf-8").splitlines()
                if "=" in l)
    want_pin = {"tag": lock.get("tag"), "commit": lock.get("commit"), "engine_tree_sha": lock.get("tree")}
    if pin != want_pin:
        problems.append(f"enginePin {pin} != superslm.lock {want_pin}")
    corpus = (REPO_ROOT / PROOF_CORPUS_PATH).read_bytes()
    rows = sum(1 for l in corpus.decode("utf-8").splitlines() if l.strip())
    if pc.get("path") != PROOF_CORPUS_PATH or pc.get("sha256") != hashlib.sha256(corpus).hexdigest() \
            or pc.get("rows") != rows:
        problems.append(f"proofCorpus path/sha256/rows {pc.get('path')}/{pc.get('sha256')}/{pc.get('rows')} != "
                        f"{PROOF_CORPUS_PATH}/{hashlib.sha256(corpus).hexdigest()}/{rows}")
    interim = sorted((REPO_ROOT / "docs" / "certification" / "interim").glob("*/token-id-digest.txt"))
    interim_digests = {f.read_text(encoding="utf-8").strip() for f in interim}
    tid = pc.get("tokenIdDigest")
    if not isinstance(tid, str) or not tid.startswith(TOKEN_ID_DIGEST_PREFIX) or interim_digests != {tid}:
        problems.append(f"tokenIdDigest {tid} (plan {TOKEN_ID_DIGEST_PREFIX}...; interim evidence {interim_digests})")
    checked = subprocess.run([sys.executable, str(tool), "--line", "1", "--root", str(REPO_ROOT), "--check"],
                             capture_output=True, text=True, timeout=120)
    if checked.returncode != 0:
        problems.append(f"write_certification_identity.py --check exit={checked.returncode}: "
                        f"{(checked.stdout + checked.stderr).strip()[-300:]}")
    status = "FAIL" if problems else "PASS"
    print(f"[{status}] IDENTITY-FILE: {doc.name} ({doc.stat().st_size} B) and its writer; "
          f"{'; '.join(problems) if problems else 'schema, pin, corpus and writer agree'}")
    cb = (REPO_ROOT / "docs" / "certified-builds.json").read_text(encoding="utf-8")
    inline_pin = '"enginePin"' in cb
    print(f"  [NOTE] docs/certified-builds.json still carries enginePin inline: {inline_pin} "
          f"(item 9 moves it to the identity file with the list's cell form, P:1138-1140; the cell-form list is "
          f"written from the re-executed interim runs)")
    return status


def cell_c54_crlf_stripped(semb_exe: Path, model: str, tokenizer: str, scratch: Path) -> str:
    if not (model and tokenizer):
        print("[MISSING PREREQUISITE] C54-CRLF-CR-KEPT: no --model/--tokenizer given")
        return "MISSING PREREQUISITE"
    if not semb_exe.exists():
        print(f"[MISSING PREREQUISITE] C54-CRLF-CR-KEPT: {semb_exe} not built")
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

    equals_no_cr = vec_stdin_crlf == vec_no_cr
    equals_with_cr = vec_stdin_crlf == vec_with_cr
    print(f"  one-shot 'hello' vector:     {vec_no_cr}")
    print(f"  one-shot 'hello\\r' vector:   {vec_with_cr}")
    print(f"  --stdin 'hello\\r\\n' vector: {vec_stdin_crlf}")
    print(f"  stdin-CRLF equals 'hello\\r'? {equals_with_cr} (required: True, stdin is read in binary mode)")
    print(f"  stdin-CRLF equals 'hello'?   {equals_no_cr} (required: False)")

    # Vitality: the two references must differ, or the comparison cannot tell a stripped CR from a kept one.
    # A synthetic tokenizer may encode both alike; only the real artifact grades this cell.
    if vec_no_cr == vec_with_cr:
        print("[MISSING PREREQUISITE] C54-CRLF-CR-KEPT: this model encodes 'hello' and 'hello\\r' identically, "
              "so the cell cannot discriminate; run it on the real artifact")
        return "MISSING PREREQUISITE"
    ok = equals_with_cr and not equals_no_cr
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] C54-CRLF-CR-KEPT: a CR before LF on --stdin is query text, as in a one-shot "
          f"query of 'hello\\r' (F19, U2-7 item 3)")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semb-exe", type=Path, default=REPO_ROOT / "build" / "msvc" / "semb.exe")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    ap.add_argument("--scratch", type=Path, default=REPO_ROOT / "build" / "_scratch" / "te331_c54")
    args = ap.parse_args()

    results = [
        cell_force_tier(),
        cell_identity_file(),
        cell_c54_crlf_stripped(args.semb_exe, args.model, args.tokenizer, args.scratch),
    ]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
