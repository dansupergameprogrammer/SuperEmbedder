"""Mint U2-9's minimal-geometry, cap-5,000 synthetic model/tokenizer pair.

te267 sec 5 U2-9, C60 (c): "A new synthetic model-and-tokenizer pair has
`context_cap` 5,000 (not a power of two) and minimal geometry: one layer, one
KV head and one query head, head_dim 8, and the smallest hidden width the
generator admits". C61, C64 and C66 (a) run on the same pair. It follows the
existing C17 regenerator's cap mechanism (tests/fixtures/wq/
regenerate_c17_highcap_pair_fixture.py), not its geometry: it reuses the pinned
U1 pair generator (same clone of the lock's tag, same converter-emitted
synthetic tokenizer, vocab 384) and replaces only the model.

HEAD_DIM IS 128, NOT 8 (a build-time item, not a plan revision). The pinned
converter refuses head_dim 8 for the QK-norm fixture model every pinned
fixture carries: `UnsupportedFusedKHeadDim: fused-QK conversion input
head_dim=8 is unsupported; required head_dim=128` (executed at v1.7.1). The
smallest geometry the generator admits is therefore one layer, one query head,
one KV head, head_dim 128 and hidden width 8, so P = 1 x 1 x 128 x 2 = 256 B
per position rather than the plan's 16 B. Every cell reads P from the handle's
geometry, never from a constant, so no cell's construction changes; only the
byte figures scale (P * 5,000 = 1,280,000 B; P * 4,096 = 1,048,576 B).

Artifacts are scratch outputs, never checked in.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
BASE = HERE.parent / "regenerate_tokenizer_pair_fixture.py"
SPEC = importlib.util.spec_from_file_location("u2_9_u1_pair_generator", BASE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load base pair generator: {BASE}")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)

CONTEXT_CAP = 5000
HIDDEN = 8
HEAD_DIM = 128


def generate_minimal_model(tools_dir: Path, out_path: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")
    config = pipeline.ModelConfig(
        hidden_size=HIDDEN, num_hidden_layers=1, num_attention_heads=1,
        num_key_value_heads=1, head_dim=HEAD_DIM, intermediate_size=64,
        vocab_size=base.PAIR_VOCAB_SIZE, rope_theta=10000.0,
        rms_norm_eps=1e-6, tie_word_embeddings=True, context_cap=CONTEXT_CAP,
    )
    model = pipeline.fixture_model(config)
    sections, _ = convert_model.build_sections(model)
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, context_cap={CONTEXT_CAP}, hidden={HIDDEN}, "
          f"layers=1, heads=1/1, head_dim={HEAD_DIM}, fingerprint={fingerprint}")


if __name__ == "__main__":
    base.generate_model = generate_minimal_model
    raise SystemExit(base.main(sys.argv[1:]))
