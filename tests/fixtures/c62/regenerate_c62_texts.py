"""tests/fixtures/c62/regenerate_c62_texts.py -- U2 cloud build, U2-9's C62
(te267 sec 5 U2-9, C62): regenerates and checks C62's two committed texts,
short.txt and long.txt.

WHAT C62 NEEDS. C62's bounds are derived for two document shapes (P:2766-2780):
a 5-token encode (n = 6 positions with the appended terminator, C = 64) and a
1,111-token encode (n = 1,112, C = 2,048). TE-398 read its figures on texts
cut from a scratch pool that no longer exists, so these replacements are cut
from a committed pool and are reproducible from git alone:
Claude/Brunel/te439-runs/fiqa-long80/ in the records repository (commit
9fa21eb9), whose fiqa-long80.tokens.tsv holds every document's content token
ids from the Qwen3-Embedding-0.6B tokenizer at snapshot
97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 (add_special_tokens=False).

THE RULE (no tokenizer needed to rebuild; the offsets were found by counting):
  short.txt  the pool's first row's text (fiqa-103125, the pool's shortest),
             its first 17 characters: "Mint.com does all" (5 content tokens).
  long.txt   every row's text in file order joined by one space (TE-387's
             make_long_doc.py joins FiQA documents the same way), its first
             5,131 characters. The cut falls before a space, after
             "Capital gains are created" in fiqa-295988 (rows 1-21 are used);
             1,111 content tokens. It is ASCII, so characters = bytes.
Each text is UTF-8, no trailing newline.

HOW THE COUNTS WERE FOUND. In the U2 cloud build, with SuperSLM's own
TokenizerView over the engine's committed Qwen2.5 tokenizer artifact
(SuperSLM tests/fixtures/qwen2.5-1.5b.tok.sslm), which shares the Qwen3
byte-level BPE vocabulary: it reproduced all 80 pool rows' committed ids
exactly, and it counts 5 and 1,111 for the two cuts (the long cut is the only
whitespace cut between 3,500 and 7,000 characters that counts 1,111). The
count under the Qwen3-Embedding-0.6B tokenizer itself is not executed here:
C62 asserts it with the product's own tokenizer artifact in every run, before
any per-document verdict (a text of any other shape emits no verdict), and
--measure below counts it with the snapshot on the dev box.

USAGE
  python regenerate_c62_texts.py --check
      Checks short.txt and long.txt against c62-texts.manifest.json (sha256 and
      bytes). No network, no tokenizer; this is the ctest leg.
  python regenerate_c62_texts.py --source-jsonl <fiqa-long80.jsonl> [--write]
      Verifies the source's sha256, applies the rule, and compares the result
      with the committed texts (--write rewrites them instead). Obtain the
      source with `git -C <records repo> show
      9fa21eb9:Claude/Brunel/te439-runs/fiqa-long80/fiqa-long80.jsonl`.
  python regenerate_c62_texts.py --measure <Qwen3-Embedding-0.6B snapshot dir>
      Counts both texts' content tokens with the snapshot's tokenizer
      (transformers, add_special_tokens=False): 5 and 1,111 are required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "c62-texts.manifest.json"

SOURCE_JSONL_SHA256 = "831cf2ed0718dede12e7129b74f15b7ddcc8c5d3a2e10cff0f7b1c50ab1da896"
SHORT_CHARS = 17
LONG_CHARS = 5131
WANT_CONTENT_TOKENS = {"short.txt": 5, "long.txt": 1111}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_committed() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = 0
    for name, want in manifest["files"].items():
        data = (HERE / name).read_bytes()
        ok = sha256(data) == want["sha256"] and len(data) == want["bytes"]
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(data)} B sha256 {sha256(data)}")
        bad += 0 if ok else 1
        ok = want["content_tokens"] == WANT_CONTENT_TOKENS[name]
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: the manifest states {want['content_tokens']} content tokens, "
              f"C62's shape is {WANT_CONTENT_TOKENS[name]}")
        bad += 0 if ok else 1
    return 1 if bad else 0


def select(jsonl: bytes) -> dict[str, str]:
    rows = [json.loads(line) for line in jsonl.decode("utf-8").splitlines() if line]
    joined = " ".join(r["text"] for r in rows)
    if joined[LONG_CHARS] != " ":
        raise SystemExit("source: the long cut does not fall before a space")
    return {"short.txt": rows[0]["text"][:SHORT_CHARS], "long.txt": joined[:LONG_CHARS]}


def regenerate(jsonl_path: Path, write: bool) -> int:
    jsonl = jsonl_path.read_bytes()
    if sha256(jsonl) != SOURCE_JSONL_SHA256:
        raise SystemExit("source: sha256 differs from the pool's SHA256SUMS")
    bad = 0
    for name, text in select(jsonl).items():
        data = text.encode("utf-8")
        if write:
            (HERE / name).write_bytes(data)
        same = (HERE / name).read_bytes() == data
        print(f"[{'PASS' if same else 'FAIL'}] {name}: {len(data)} B, sha256 {sha256(data)}")
        bad += 0 if same else 1
    return 1 if bad else 0


def measure(snapshot: Path) -> int:
    from transformers import AutoTokenizer  # the dev box's; not needed by --check

    tok = AutoTokenizer.from_pretrained(str(snapshot))
    bad = 0
    for name, want in WANT_CONTENT_TOKENS.items():
        text = (HERE / name).read_bytes().decode("utf-8")
        got = len(tok(text, add_special_tokens=False)["input_ids"])
        print(f"[{'PASS' if got == want else 'FAIL'}] {name}: {got} content tokens (want {want}; "
              f"{got + 1} positions with the terminator)")
        bad += 0 if got == want else 1
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source-jsonl", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--measure", type=Path)
    a = ap.parse_args()
    if a.check:
        return check_committed()
    if a.source_jsonl:
        return regenerate(a.source_jsonl, a.write)
    if a.measure:
        return measure(a.measure)
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
