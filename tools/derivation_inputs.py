#!/usr/bin/env python3
"""tools/derivation_inputs.py -- the SHA-256 over a tree's derivation inputs (plan U2-3 item 4, F5).

A certification run records this digest in its run.json (`derivationInputsSha256`) beside the product commit,
and C42 (c') refuses a run whose digest differs from the tree being certified, so a SuperEmbedder source change
after the runs leaves no proof "fresh".

The inputs are te140 sec 4.7's re-run list: src/, include/, cmake/, CMakeLists.txt, superslm.lock,
src/superembedder/wb_corpus.cpp and tests/fixtures/wq/. Both certification files are excluded: the list is
written from these runs, and the identity file is graded by C42 (h) from superslm.lock and the proof corpus.

The digest is SHA-256 over the path-sorted sequence u64 BE len(path) || path || u64 BE len(bytes) || bytes, each
path relative to the root in POSIX form, over every regular file under the inputs as they are on disk (the
repository's `* -text` attribute makes the bytes identical on every checkout).

    python tools/derivation_inputs.py [--root <repo>]      prints DERIVATION_INPUTS_SHA256=<digest>
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

INPUTS = ("src", "include", "cmake", "CMakeLists.txt", "superslm.lock", "src/superembedder/wb_corpus.cpp",
          "tests/fixtures/wq")
EXCLUDED_DIR_NAMES = {"__pycache__"}


def input_files(root: Path) -> list[str]:
    found: set[str] = set()
    for entry in INPUTS:
        path = root / entry
        if path.is_file():
            found.add(entry)
        elif path.is_dir():
            for p in path.rglob("*"):
                if p.is_file() and not EXCLUDED_DIR_NAMES.intersection(p.relative_to(root).parts):
                    found.add(p.relative_to(root).as_posix())
        else:
            raise FileNotFoundError(f"derivation input {entry} does not exist under {root}")
    return sorted(found)


def digest(root: Path) -> str:
    h = hashlib.sha256()
    for rel in input_files(root):
        data = (root / rel).read_bytes()
        name = rel.encode("utf-8")
        h.update(len(name).to_bytes(8, "big") + name + len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    print(f"DERIVATION_INPUTS_SHA256={digest(args.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
