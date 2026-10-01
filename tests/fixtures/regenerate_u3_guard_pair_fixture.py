"""Mint U3 row 5(a)'s guard-refusal pair (te266 sec 4.6 row 5(a), P:4215; TE-389 G1).

The construction, as the plan states it: the U1 pair model with embedding rows
121 and 173 exchanged, and `layer0.attn_norm`'s mantissa set to
m = -679,477,248 with the exponent unchanged, re-sealed as A2-fn does. Re-sealing
here is the engine's own `sslm_format.build_artifact`, which writes the
integrity SHA-256 over the finished file, so the output is sealed exactly as a
converter-built artifact is (A2-fn's hand re-seal computes the same hash over
the same bytes, P:764).

The exchange is made on the model's int8 embedding table before the sections
are built (the embedding is a lookup table: exchanging two rows exchanges what
ids 121 and 173 embed to and changes no arithmetic). The constant is set on
the model's composition constants before `build_sections` writes them.

Everything else -- the tokenizer, the no-endoftext tokenizer, the expected-ids
table and the manifest -- is the pinned U1 generator's
(regenerate_tokenizer_pair_fixture.py), which this wrapper reuses unchanged.

The cell's own CPU oracle (tests/u3_guard_fixture_test.cpp) reproduces the
one-id trip set on the minted file before any cell reads it (P:4215, "Setup
precondition").

USAGE: python tests/fixtures/regenerate_u3_guard_pair_fixture.py \
           --lock superslm.lock --out-dir build/_scratch/u3_guard_pair
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BASE = HERE.parent / "regenerate_tokenizer_pair_fixture.py"
SPEC = importlib.util.spec_from_file_location("u3_guard_pair_base", BASE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load base pair generator: {BASE}")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)

SWAP_A, SWAP_B = 121, 173           # 'y' and byte 0xAD (P:4215)
ATTN_NORM_KEY = "layer0.attn_norm"
ATTN_NORM_M = -679_477_248          # P:4215


def generate_guard_model(tools_dir: Path, out_path: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")
    cfg = pipeline.ModelConfig(
        hidden_size=32, num_hidden_layers=8, num_attention_heads=4,
        num_key_value_heads=2, head_dim=128, intermediate_size=64, vocab_size=base.PAIR_VOCAB_SIZE,
        rope_theta=10000.0, rms_norm_eps=1e-6, tie_word_embeddings=True, context_cap=64,
    )
    model = pipeline.fixture_model(cfg)
    embed = model.weights["embed"]
    if embed.shape[0] != base.PAIR_VOCAB_SIZE:
        raise SystemExit(f"embed table has {embed.shape[0]} rows, expected {base.PAIR_VOCAB_SIZE}")
    row_a = embed[SWAP_A].copy()
    embed[SWAP_A] = embed[SWAP_B]
    embed[SWAP_B] = row_a
    if ATTN_NORM_KEY not in model.composition_constants:
        raise SystemExit(f"composition constant {ATTN_NORM_KEY} is absent")
    old_m, old_e = model.composition_constants[ATTN_NORM_KEY]
    model.composition_constants[ATTN_NORM_KEY] = (ATTN_NORM_M, int(old_e))
    sections, _ = convert_model.build_sections(model)
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, embed rows {SWAP_A}<->{SWAP_B} exchanged, "
          f"{ATTN_NORM_KEY} ({int(old_m)}, {int(old_e)}) -> ({ATTN_NORM_M}, {int(old_e)}), "
          f"fingerprint={fingerprint}")


if __name__ == "__main__":
    base.generate_model = generate_guard_model
    raise SystemExit(base.main(sys.argv[1:]))
