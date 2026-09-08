"""tests/epoch_store_contract.py -- TE-162 (U1 slice 3 red suite): the
Python sibling of tests/semb_epoch_store_contract.h -- the SAME contract,
kept in sync BY HAND (this project's own established convention;
tests/semb_seam_abi_contract.h's own header comment names the identical
practice for a C++-side mirror). See that header for the full rationale
and the sec 8 C32 citations; this module states the identical shape without
repeating the citations, and both files' own docstrings/comments say so
explicitly so neither is mistaken for the sole source.

WHAT THIS MODULE HOLDS: pure path/format constants and format helpers
(SHA-256, little-endian u64 packing, TSV read/write) -- no product code, no
subprocess calls, no git calls. tests/epoch_store_check.py and
tests/epoch_store_constructions_check.py both import this module rather
than each defining their own copy, so a fixed-point drift between the two
checkers is impossible by construction; the C++ side
(tests/semb_epoch_store_contract.h, tests/c2_lineage_equality_test.cpp)
necessarily stays a hand-kept mirror since Python and C++ share no header.
"""
from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

LIVE_DIR = "epoch-store/live"
ARCHIVE_DIR = "epoch-store/archive"

VECTORS_FILE_NAME = "vectors.f32"
ROW_DIGEST_FILE_NAME = "row-digest.tsv"
LINEAGE_FILE_NAME = "lineage.tsv"

STATUS_BYTES_DIVERGED = "SEMB_EPOCH_BYTES_DIVERGED"
STATUS_LINEAGE_DIVERGED = "SEMB_EPOCH_LINEAGE_DIVERGED"
STATUS_ENTRY_MODIFIED = "SEMB_EPOCH_ENTRY_MODIFIED"

FINGERPRINT_BYTES = 32
FINGERPRINT_HEX_CHARS = 64

MEMBER_FILE_NAMES = (VECTORS_FILE_NAME, ROW_DIGEST_FILE_NAME, LINEAGE_FILE_NAME)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u64_le(value: int) -> bytes:
    return struct.pack("<Q", value)


def is_fingerprint_dir_name(name: str) -> bool:
    if len(name) != FINGERPRINT_HEX_CHARS:
        return False
    try:
        int(name, 16)
    except ValueError:
        return False
    return name == name.lower()


def entry_dir(store_root: Path, section: str, fingerprint_hex: str) -> Path:
    """`section` is LIVE_DIR or ARCHIVE_DIR; `store_root` is the repository
    root (the parent of "epoch-store/"), matching how the C++ contract
    states paths relative to the product repository root."""
    return store_root / section / fingerprint_hex


def list_live_fingerprints(repo_root: Path) -> List[str]:
    live = repo_root / LIVE_DIR
    if not live.is_dir():
        return []
    return sorted(p.name for p in live.iterdir() if p.is_dir() and is_fingerprint_dir_name(p.name))


def list_archive_fingerprints(repo_root: Path) -> List[str]:
    archive = repo_root / ARCHIVE_DIR
    if not archive.is_dir():
        return []
    return sorted(p.name for p in archive.iterdir() if p.is_dir() and is_fingerprint_dir_name(p.name))


def parse_row_digest_tsv(text: str) -> Tuple[Dict[str, str], str]:
    """Returns (per-doc id -> psn_vector_sha256, the "all" line's own
    value). Raises ValueError on a line that does not carry exactly two
    tab-separated fields, or a file with no trailing "all" line -- a
    malformed file is a FAIL, never a silent partial read."""
    per_doc: Dict[str, str] = {}
    all_value = None
    lines = [ln for ln in text.split("\n") if ln != ""]
    for ln in lines:
        parts = ln.split("\t")
        if len(parts) != 2:
            raise ValueError(f"row-digest.tsv line is not exactly id<TAB>digest: {ln!r}")
        key, value = parts
        if key == "all":
            all_value = value
        else:
            per_doc[key] = value
    if all_value is None:
        raise ValueError("row-digest.tsv carries no trailing 'all' line")
    return per_doc, all_value


def parse_lineage_tsv(text: str) -> Tuple[Dict[str, str], str]:
    """Identical shape to parse_row_digest_tsv -- lineage.tsv's own format
    is "<id>\\t<seam_sha256>\\n" per document then "all\\t<...>\\n"."""
    return parse_row_digest_tsv(text)


def format_row_digest_tsv(per_doc: List[Tuple[str, str]], all_value: str) -> str:
    lines = [f"{doc_id}\t{digest}" for doc_id, digest in per_doc]
    lines.append(f"all\t{all_value}")
    return "\n".join(lines) + "\n"


def format_lineage_tsv(per_doc: List[Tuple[str, str]], all_value: str) -> str:
    return format_row_digest_tsv(per_doc, all_value)


def ensure_synthetic_pair(repo_root: Path) -> Tuple[str, str]:
    """Regenerates (or reuses, if already present) the ALREADY-TOKENIZER-
    CAPABLE synthetic model+tokenizer pair
    tests/fixtures/regenerate_tokenizer_pair_fixture.py mints (vocab 384,
    hidden 32, context_cap 64, <|endoftext|>=262) -- NOT
    regenerate_synthetic_artifact.py's own single-file fixture (hidden 32,
    vocab 128), which was tried first this round and refused at
    semb_encoder_open (SEMB_ENGINE_REFUSED, confirmed by execution): that
    fixture carries no real tokenizer structure, per
    regenerate_tokenizer_pair_fixture.py's own header comment ("a byte-
    level BPE tokenizer needs 256 base ids before any merge or special, so
    its ids do not fit a 128-entry vocabulary") -- exactly why that script
    exists. tests/c2_lineage_equality_test.cpp's own EnsureSyntheticPairForC2()
    is the C++-side twin of this function, same cache path convention
    (build/_scratch/u1_pair/), so a run of either reuses the other's mint.
    Returns (model_path, tokenizer_path), both absolute."""
    out_dir = repo_root / "build" / "_scratch" / "u1_pair"
    model = out_dir / "u1_pair_model.sslm"
    tokenizer = out_dir / "u1_pair_tokenizer.sslm"
    if model.is_file() and tokenizer.is_file():
        return str(model), str(tokenizer)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(repo_root / "tests" / "fixtures" / "regenerate_tokenizer_pair_fixture.py"),
           "--lock", "superslm.lock", "--out-dir", str(out_dir)]
    env_source = os.environ.get("SEMB_TEST_ENGINE_SOURCE", "")
    if env_source:
        cmd += ["--source", env_source]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"regenerate_tokenizer_pair_fixture.py failed: {proc.stdout}\n{proc.stderr}")
    return str(model), str(tokenizer)


def read_tokens_tsv(path: Path) -> List[Tuple[str, List[int]]]:
    """tests/fixtures/c12b/corpus-239.tokens.tsv's own format:
    "<id>\\t<comma-separated content token ids>\\n", no terminator
    appended (the terminator is a separate, corpus-level fact -- 151643 for
    the real corpus per its own manifest, a fixed in-vocab id for the
    synthetic corpus, both passed in by the caller, never hardcoded here)."""
    out: List[Tuple[str, List[int]]] = []
    for ln in path.read_text(encoding="utf-8").split("\n"):
        if ln == "":
            continue
        doc_id, ids_field = ln.split("\t")
        ids_field = ids_field.strip()
        ids = [int(x) for x in ids_field.split(",")] if ids_field else []
        out.append((doc_id, ids))
    return out
