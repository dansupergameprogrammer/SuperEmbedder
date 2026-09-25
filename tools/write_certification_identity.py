#!/usr/bin/env python3
"""tools/write_certification_identity.py -- writes docs/certification-identity.json, the only writer of it
(plan U2-3 item 9; FORMAT.md sec 4).

A certified cell's certification_epoch is the SHA-256 of this file's exact bytes; an uncertified build's is the
SHA-256 of "SEMB-UNCERTIFIED\\0" followed by them. The file holds the engine pin and the proof corpus and nothing
else, so adding cells to docs/certified-builds.json never moves the epoch.

  enginePin    tag, commit and engine_tree_sha (`tree=`), read from superslm.lock
  proofCorpus  path, the corpus file's SHA-256, rows, corpusDigest (the bake manifest's corpus_digest rule: u64 LE
               count, then per row u64 LE len(label) || label || u64 LE len(text) || text) and tokenIdDigest
               (C23's rule over the corpus's committed content_ids: per row u64 LE count, then each id u32 LE)
  line         from --line

Canonical form: ASCII, LF, two-space indentation, members in the order above, one trailing LF.

    python tools/write_certification_identity.py --line 1 [--root <repo>] [--out <path>] [--check]

--check writes nothing and exits 1 when the committed file differs by a byte from what this tool writes
(C42 (h)'s rule).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

CORPUS_PATH = "tests/fixtures/c12b/corpus-239.jsonl"
IDENTITY_PATH = "docs/certification-identity.json"


def read_lock(path: Path) -> dict:
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            fields[k.strip()] = v.strip()
    missing = [k for k in ("tag", "commit", "tree") if not fields.get(k)]
    if missing:
        raise ValueError(f"{path} carries no {', '.join(missing)}")
    return fields


def corpus_rows(corpus: bytes) -> list[dict]:
    return [json.loads(line) for line in corpus.decode("utf-8").splitlines() if line.strip()]


def corpus_digest(rows: list[dict]) -> str:
    h = hashlib.sha256(struct.pack("<Q", len(rows)))
    for r in rows:
        label, text = r["label"].encode("utf-8"), r["text"].encode("utf-8")
        h.update(struct.pack("<Q", len(label)) + label + struct.pack("<Q", len(text)) + text)
    return h.hexdigest()


def token_id_digest(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for r in rows:
        ids = r["content_ids"]
        h.update(struct.pack("<Q", len(ids)) + struct.pack(f"<{len(ids)}I", *ids))
    return h.hexdigest()


def identity_bytes(root: Path, line: int) -> bytes:
    lock = read_lock(root / "superslm.lock")
    corpus = (root / CORPUS_PATH).read_bytes()
    rows = corpus_rows(corpus)
    doc = {
        "schemaVersion": 1,
        "product": "superembedder",
        "line": line,
        "enginePin": {"tag": lock["tag"], "commit": lock["commit"], "engine_tree_sha": lock["tree"]},
        "proofCorpus": {
            "path": CORPUS_PATH,
            "sha256": hashlib.sha256(corpus).hexdigest(),
            "rows": len(rows),
            "corpusDigest": corpus_digest(rows),
            "tokenIdDigest": token_id_digest(rows),
        },
    }
    return (json.dumps(doc, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--line", type=int, required=True)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--out", type=Path, default=None, help=f"default: <root>/{IDENTITY_PATH}")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.line < 1:
        ap.error("--line starts at 1")
    out = args.out or args.root / IDENTITY_PATH
    data = identity_bytes(args.root, args.line)
    if args.check:
        current = out.read_bytes() if out.is_file() else None
        if current != data:
            print(f"SEMB_CERTIFICATION_IDENTITY_STALE: {out} differs from what this tool writes from "
                  f"{args.root / 'superslm.lock'} and {CORPUS_PATH} at line {args.line}")
            return 1
        print(f"{out}: current ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"wrote {out}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
