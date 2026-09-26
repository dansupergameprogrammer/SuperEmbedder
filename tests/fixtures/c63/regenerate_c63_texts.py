"""tests/fixtures/c63/regenerate_c63_texts.py -- U2 cloud build, U2-10's C63
(te267 sec 5 U2-10, C63): regenerates and checks C63's two committed texts,
mid.txt and short.txt.

WHY THEY ARE COMMITTED. C63's first texts were the adversary's mid.txt (603 B,
133 positions) and short.txt (34 B), cut from a FiQA pool on the dev box's
scratch drive. That pool was deleted and cannot be rebuilt. The replacements
are cut from a committed pool, so they are reproducible from git alone:
Claude/Brunel/te439-runs/fiqa-long80/ in the records repository (commit
9fa21eb9), whose fiqa-long80.tokens.tsv holds every document's content token
ids from the Qwen3-Embedding-0.6B tokenizer at snapshot
97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 (add_special_tokens=False).

THE RULE (the adversary's generator, where it still applies):
  short.txt  the pool's first row, i.e. its shortest document (the pool is
             sorted by (content tokens, id)); the adversary's generator also
             took the first row of its short-document file.
  mid.txt    the pool's one document with exactly 132 content tokens, whole:
             132 + the appended terminator (151643) = 133 positions, the
             adversary's mid.txt's measured shape. The adversary cut its
             mid.txt from a longer document at whitespace; a cut's position
             count needs the tokenizer, and the pool's committed ids measure
             whole documents only, so the whole document is taken.
Each text is the row's `text` field, UTF-8, no trailing newline (the
adversary's generator wrote the field with newline="").

USAGE
  python regenerate_c63_texts.py --check
      Checks mid.txt and short.txt against c63-texts.manifest.json (sha256
      and bytes). No network, no tokenizer; this is the ctest leg.
  python regenerate_c63_texts.py --source-jsonl <fiqa-long80.jsonl>
                                 --source-tokens <fiqa-long80.tokens.tsv>
                                 [--write]
      Verifies the two source files' sha256 against the pool's SHA256SUMS,
      applies the rule, and compares the result with the committed texts
      (--write rewrites them instead). Obtain the sources with
      `git -C <records repo> show 9fa21eb9:Claude/Brunel/te439-runs/fiqa-long80/<file>`.
  python regenerate_c63_texts.py --measure <Qwen3-Embedding-0.6B snapshot dir>
      Counts, with the snapshot's tokenizer (transformers), the positions C63
      states before its run: the mid document's (content + terminator), and
      the query leg's, which is the product's composed query (the query
      instruction prefix immediately followed by mid.txt, src/superembedder/
      query.cpp) plus the terminator. The prefix's last character joins the
      document's first word in pre-tokenization, so the query count is not
      the prefix's count plus the document's; it is measured, never summed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "c63-texts.manifest.json"
QUERY_PREFIX_SOURCE = HERE.parent.parent.parent / "src" / "superembedder" / "query.cpp"

SOURCE_JSONL_SHA256 = "831cf2ed0718dede12e7129b74f15b7ddcc8c5d3a2e10cff0f7b1c50ab1da896"
SOURCE_TOKENS_SHA256 = "9453461fd3132f57ff42e395b2973f3f064b44a20882cc18ca9c7227be214e8a"
MID_CONTENT_TOKENS = 132  # + the appended terminator = 133 positions
QUERY_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"


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
    src = QUERY_PREFIX_SOURCE.read_text(encoding="utf-8") if QUERY_PREFIX_SOURCE.exists() else ""
    literal = QUERY_PREFIX.replace("\n", "\\n")
    ok = f'"{literal}"' in src
    print(f"[{'PASS' if ok else 'FAIL'}] the query prefix this script measures with is query.cpp's kQueryPrefix")
    bad += 0 if ok else 1
    return 1 if bad else 0



def select(jsonl: bytes, tokens: bytes) -> dict[str, tuple[str, str, int]]:
    rows = [json.loads(line) for line in jsonl.decode("utf-8").splitlines() if line]
    counts = {}
    for line in tokens.decode("utf-8").splitlines():
        if line:
            label, ids = line.split("\t")
            counts[label] = len(ids.split(","))
    if [r["id"] for r in rows] != list(counts):
        raise SystemExit("source: the jsonl and the tokens file list different rows")
    mids = [r for r in rows if counts[r["id"]] == MID_CONTENT_TOKENS]
    if len(mids) != 1:
        raise SystemExit(f"source: {len(mids)} rows with {MID_CONTENT_TOKENS} content tokens, want exactly 1")
    first = rows[0]
    return {
        "short.txt": (first["id"], first["text"], counts[first["id"]]),
        "mid.txt": (mids[0]["id"], mids[0]["text"], counts[mids[0]["id"]]),
    }


def regenerate(jsonl_path: Path, tokens_path: Path, write: bool) -> int:
    jsonl, tokens = jsonl_path.read_bytes(), tokens_path.read_bytes()
    if sha256(jsonl) != SOURCE_JSONL_SHA256 or sha256(tokens) != SOURCE_TOKENS_SHA256:
        raise SystemExit("source: sha256 differs from the pool's SHA256SUMS")
    bad = 0
    for name, (label, text, content) in select(jsonl, tokens).items():
        data = text.encode("utf-8")
        if write:
            (HERE / name).write_bytes(data)
        same = (HERE / name).read_bytes() == data
        print(f"[{'PASS' if same else 'FAIL'}] {name} = {label}: {len(data)} B, {content} content tokens, "
              f"{content + 1} positions, sha256 {sha256(data)}")
        bad += 0 if same else 1
    return 1 if bad else 0


def measure(snapshot: Path) -> int:
    from transformers import AutoTokenizer  # the dev box's; not needed by --check

    tok = AutoTokenizer.from_pretrained(str(snapshot))
    mid = (HERE / "mid.txt").read_bytes().decode("utf-8")
    doc = len(tok(mid, add_special_tokens=False)["input_ids"]) + 1
    query = len(tok(QUERY_PREFIX + mid, add_special_tokens=False)["input_ids"]) + 1
    print(f"mid positions {doc} (manifest: 133)")
    print(f"query-leg positions {query}")
    return 0 if doc == 133 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source-jsonl", type=Path)
    ap.add_argument("--source-tokens", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--measure", type=Path)
    a = ap.parse_args()
    if a.check:
        return check_committed()
    if a.source_jsonl and a.source_tokens:
        return regenerate(a.source_jsonl, a.source_tokens, a.write)
    if a.measure:
        return measure(a.measure)
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
