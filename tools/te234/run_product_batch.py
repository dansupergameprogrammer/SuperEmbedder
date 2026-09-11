#!/usr/bin/env python3
"""Run one TE-234 corpus arm through product_batch.cpp."""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
from pathlib import Path


QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query:"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("query", "document"), required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line]
    texts = [
        QUERY_PREFIX + row["text"] if args.kind == "query" else row["text"]
        for row in rows
    ]
    payload = bytearray()
    for text in texts:
        encoded = text.encode("utf-8")
        payload.extend(struct.pack("<Q", len(encoded)))
        payload.extend(encoded)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(args.exe), str(args.model), str(args.tokenizer), str(args.out)],
        input=bytes(payload),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=419,
        check=True,
    )
    print(completed.stdout.decode("utf-8"), end="")
    print(completed.stderr.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
