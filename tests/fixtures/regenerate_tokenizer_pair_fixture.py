"""tests/fixtures/regenerate_tokenizer_pair_fixture.py -- TE-92 (U1, the frozen
raw-text slice's red suite): regenerates the SYNTHETIC MODEL + TOKENIZER PAIR
the mechanism cells of tests/u1_raw_text_contract_test.cpp and
tests/u1_raw_text_parity_test.cpp open through the frozen `semb_encoder_open`
(`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1), plus the expected token ids
of the committed mechanism corpus, computed by the pinned converter's OWN
reference encoder.

WHY A PAIR, AND WHY A SECOND SYNTHETIC MODEL. The existing synthetic fixture
(regenerate_synthetic_artifact.py: hidden 32, vocab 128, context_cap 64)
cannot be tokenized into: a byte-level BPE tokenizer needs 256 base ids
before any merge or special, so its ids do not fit a 128-entry vocabulary.
This script builds, from the SAME pinned engine tools the sibling
regenerators import (hermetic clone of the exact `superslm.lock` tag,
deleted afterward, artifact never committed):

  <out-dir>/u1_pair_model.sslm      the T-2199 fixture config with
                                    vocab_size=384 (>= 256 bytes + 6 merges
                                    + 3 specials = 265, rounded to the same
                                    multiple of 128 real Qwen configs use);
                                    every other field unchanged (hidden 32,
                                    8 layers, heads 4/2, intermediate 64,
                                    context_cap 64) except head_dim 128:
                                    the pinned engine admits a QK-norm
                                    (fused-K) artifact only at head_dim
                                    128, and the header flags come from
                                    the engine's own
                                    artifact_flags_for_model()
  <out-dir>/u1_pair_tokenizer.sslm  tools/convert_tokenizer.py's REAL
                                    emit_artifact() run over the committed
                                    synthetic checkpoint
                                    tests/fixtures/tokenizer/u1-synthetic-checkpoint/
                                    (256 byte ids, 6 merges at ids 256..261,
                                    specials <|endoftext|>=262, <|im_end|>=263,
                                    <|im_start|>=264, and the candidate's own
                                    post_processor shape appending 262)
  <out-dir>/u1_pair_tokenizer_no_endoftext.sslm
                                    TE-94 (D-SLM6314 re-entry, P-1/P-4): the SAME
                                    converter run over the committed VARIANT
                                    checkpoint
                                    tests/fixtures/tokenizer/u1-synthetic-checkpoint-no-endoftext/
                                    -- the identical byte-level BPE vocabulary
                                    and merges, a special table carrying
                                    <|im_end|>=262 and <|im_start|>=263 ONLY
                                    (no <|endoftext|>), and a bare ByteLevel
                                    post-processor (no trailing special). It
                                    loads through the engine's own TokenizerView
                                    and fits the 384-vocab model's join, so the
                                    ONLY thing wrong with it is that the
                                    compiled-in end-token literal resolves to
                                    no single id: the absent-template cell
                                    (K-06f) reaches SEMB_TEMPLATE_TOKEN_ABSENT
                                    through this artifact rather than a
                                    loader or join refusal
  <out-dir>/u1_mechanism_expected_ids.tsv
                                    `<label>\t<comma-separated content ids>\t<utf8 hex>`
                                    for every record of
                                    tests/fixtures/tokenizer/u1-mechanism-corpus.jsonl,
                                    ids = TokenizerTables.ref_encode(text) --
                                    the converter's reference algorithm
                                    (proven byte-for-byte against the
                                    upstream HF tokenizer on real
                                    checkpoints), which takes NO input from
                                    SuperEmbedder or from the engine's C++
                                    TokenizerView. The empty record is
                                    written with an empty id column.
  <out-dir>/u1_pair.manifest.json   SHA-256 of all four, the pinned tag,
                                    and both checkpoints' files' SHA-256, so a
                                    cell can refuse a stale scratch pair by
                                    name.

USAGE
  python tests/fixtures/regenerate_tokenizer_pair_fixture.py \\
      --lock superslm.lock --out-dir build/_scratch/u1_pair
      [--source <path-or-url>] [--workdir <scratch dir>]

Exit codes: 0 success; 1 usage/environment error; 2 clone/generation failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_mint_guard as mint_guard  # noqa: E402 -- per-process workdir, per-output mint lock

DEFAULT_REMOTE = "https://github.com/dansupergameprogrammer/SuperSLM.git"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # tests/fixtures/<this file>
CHECKPOINT = REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "u1-synthetic-checkpoint"
CHECKPOINT_NO_ENDOFTEXT = REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "u1-synthetic-checkpoint-no-endoftext"
MECHANISM_CORPUS = REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "u1-mechanism-corpus.jsonl"
PAIR_VOCAB_SIZE = 384
PAIR_APPENDED_TOKEN_ID = 262  # <|endoftext|> in the synthetic checkpoint
CANONICAL_END_TOKEN = "<|endoftext|>"  # the literal the product resolves at open (plan sec 3.2)


def _rmtree_onerror(func, path, exc_info):
    import os
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_lock_tag(lock_path: Path) -> str:
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("tag="):
            return line[len("tag="):]
    raise ValueError(f"{lock_path}: no 'tag=' line found")


def clone_engine_tools(tag: str, source: str, workdir: Path) -> Path:
    rmtree(workdir)
    workdir.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
         "--branch", tag, "--single-branch", source, str(workdir)],
        check=True,
    )
    return workdir


def generate_model(tools_dir: Path, out_path: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")
    # The T-2199 fixture config (tools/_t2199_s8_synthetic_full_model_fixture.py
    # in the pinned clone), vocab widened to PAIR_VOCAB_SIZE and nothing else.
    cfg = pipeline.ModelConfig(
        hidden_size=32, num_hidden_layers=8, num_attention_heads=4,
        num_key_value_heads=2, head_dim=128, intermediate_size=64, vocab_size=PAIR_VOCAB_SIZE,
        rope_theta=10000.0, rms_norm_eps=1e-6, tie_word_embeddings=True, context_cap=64,
    )
    model = pipeline.fixture_model(cfg)
    sections, _fold_err = convert_model.build_sections(model)
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, vocab_size={PAIR_VOCAB_SIZE}, fingerprint={fingerprint}")


def generate_tokenizer_and_ids(tools_dir: Path, tok_out: Path, ids_out: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    import importlib
    ct = importlib.import_module("convert_tokenizer")
    tables = ct.TokenizerTables(str(CHECKPOINT))
    if tables.trailing_special_id != PAIR_APPENDED_TOKEN_ID:
        raise RuntimeError(f"synthetic checkpoint's trailing special id is {tables.trailing_special_id}, "
                           f"expected {PAIR_APPENDED_TOKEN_ID}")
    fp = tables.emit_artifact(str(tok_out))
    print(f"wrote {tok_out}: {tok_out.stat().st_size} bytes, fingerprint={fp}, "
          f"trailing_special_id={tables.trailing_special_id}")
    lines = ct.read_corpus_records(str(MECHANISM_CORPUS))
    with open(ids_out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# label\tcontent_ids\ttext_utf8_hex -- ids from convert_tokenizer.TokenizerTables.ref_encode "
                "over tests/fixtures/tokenizer/u1-mechanism-corpus.jsonl; empty ids = the empty record\n")
        for i, text in enumerate(lines):
            ids = tables.ref_encode(text) if text else []
            f.write("m-%03d\t%s\t%s\n" % (i, ",".join(str(x) for x in ids), text.encode("utf-8").hex()))
    print(f"wrote {ids_out}: {len(lines)} records")


def generate_no_endoftext_tokenizer(tools_dir: Path, tok_out: Path) -> None:
    """TE-94: the variant artifact for the absent-template cell. Emitted by the
    identical pinned converter over the committed variant checkpoint. Refuses
    by name if the variant does not have the shape the cell depends on: no
    <|endoftext|> in its special table, no trailing special from its
    post-processor, and every id inside the 384-vocab model's join."""
    sys.path.insert(0, str(tools_dir))
    import importlib
    ct = importlib.import_module("convert_tokenizer")
    tables = ct.TokenizerTables(str(CHECKPOINT_NO_ENDOFTEXT))
    if tables.trailing_special_id is not None:
        raise RuntimeError(f"variant checkpoint's post-processor appends special id "
                           f"{tables.trailing_special_id}; the variant must append nothing")
    if CANONICAL_END_TOKEN in tables.special_ids:
        raise RuntimeError(f"variant checkpoint's special table carries {CANONICAL_END_TOKEN!r}; "
                           f"the variant must not")
    vocab_count = len(tables.id_to_bytes)
    if vocab_count > PAIR_VOCAB_SIZE:
        raise RuntimeError(f"variant vocab_count {vocab_count} exceeds the pair model's vocab_size "
                           f"{PAIR_VOCAB_SIZE}; the absent-template cell must not reach the join refusal")
    # The literal must NOT resolve to exactly one id through the reference
    # encoder either -- the same algorithm the engine's TokenizerView runs.
    literal_ids = tables.ref_encode(CANONICAL_END_TOKEN)
    if len(literal_ids) == 1:
        raise RuntimeError(f"variant encodes {CANONICAL_END_TOKEN!r} to a single id {literal_ids}; "
                           f"the absent-template cell could not fire on it")
    fp = tables.emit_artifact(str(tok_out))
    print(f"wrote {tok_out}: {tok_out.stat().st_size} bytes, fingerprint={fp}, "
          f"specials={tables.specials}, vocab_count={vocab_count}, "
          f"{CANONICAL_END_TOKEN!r} -> {len(literal_ids)} ids")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="superslm.lock")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source", default=DEFAULT_REMOTE)
    # Empty = a directory of this process's own (fixture_mint_guard.private_workdir).
    ap.add_argument("--workdir", default="")
    args = ap.parse_args(argv)

    lock_path = Path(args.lock)
    if not lock_path.exists():
        print(f"SEMB_FIXTURE_LOCK_MISSING: {lock_path} does not exist.", file=sys.stderr)
        return 1
    for req in (CHECKPOINT / "tokenizer.json", CHECKPOINT / "tokenizer_config.json",
                CHECKPOINT_NO_ENDOFTEXT / "tokenizer.json", CHECKPOINT_NO_ENDOFTEXT / "tokenizer_config.json",
                MECHANISM_CORPUS):
        if not req.exists():
            print(f"SEMB_FIXTURE_INPUT_MISSING: {req}", file=sys.stderr)
            return 1
    tag = read_lock_tag(lock_path)
    started = mint_guard.now()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "u1_pair.manifest.json"
    _held = mint_guard.hold_output_lock(manifest_path)  # noqa: F841 -- held until exit
    if mint_guard.minted_since(manifest_path, started):
        print(f"{out_dir}: minted by a concurrent run while this one waited for it; reusing it")
        return 0
    print(f"regenerating the U1 synthetic model+tokenizer pair from pinned tag {tag}")

    workdir = mint_guard.private_workdir(args.workdir, "_u1_pair_fixture_workdir")
    try:
        clone = clone_engine_tools(tag, args.source, workdir)
    except subprocess.CalledProcessError as ex:
        print(f"SEMB_FIXTURE_CLONE_FAILED: {ex}", file=sys.stderr)
        return 2

    model_out = out_dir / "u1_pair_model.sslm"
    tok_out = out_dir / "u1_pair_tokenizer.sslm"
    tok_no_eot_out = out_dir / "u1_pair_tokenizer_no_endoftext.sslm"
    ids_out = out_dir / "u1_mechanism_expected_ids.tsv"
    try:
        generate_model(clone / "tools", model_out)
        generate_tokenizer_and_ids(clone / "tools", tok_out, ids_out)
        generate_no_endoftext_tokenizer(clone / "tools", tok_no_eot_out)
    except Exception as ex:  # noqa: BLE001 -- reported, not swallowed
        print(f"SEMB_FIXTURE_GENERATION_FAILED: {type(ex).__name__}: {ex}", file=sys.stderr)
        rmtree(workdir)
        return 2
    rmtree(workdir)

    manifest = {
        "schema": "semb_u1_pair_fixture_manifest_v2",
        "engine_tag": tag,
        "vocab_size": PAIR_VOCAB_SIZE,
        "appended_token_id": PAIR_APPENDED_TOKEN_ID,
        "checkpoint": {
            "tokenizer_json_sha256": sha256_file(CHECKPOINT / "tokenizer.json"),
            "tokenizer_config_json_sha256": sha256_file(CHECKPOINT / "tokenizer_config.json"),
        },
        "checkpoint_no_endoftext": {
            "tokenizer_json_sha256": sha256_file(CHECKPOINT_NO_ENDOFTEXT / "tokenizer.json"),
            "tokenizer_config_json_sha256": sha256_file(CHECKPOINT_NO_ENDOFTEXT / "tokenizer_config.json"),
        },
        "mechanism_corpus_sha256": sha256_file(MECHANISM_CORPUS),
        "files": {
            model_out.name: {"sha256": sha256_file(model_out), "bytes": model_out.stat().st_size},
            tok_out.name: {"sha256": sha256_file(tok_out), "bytes": tok_out.stat().st_size},
            tok_no_eot_out.name: {"sha256": sha256_file(tok_no_eot_out), "bytes": tok_no_eot_out.stat().st_size},
            ids_out.name: {"sha256": sha256_file(ids_out), "bytes": ids_out.stat().st_size},
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                                   encoding="utf-8", newline="\n")
    print(json.dumps(manifest["files"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
