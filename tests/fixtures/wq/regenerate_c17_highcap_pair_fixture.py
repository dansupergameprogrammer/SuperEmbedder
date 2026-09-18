"""Mint C17's disposable high-context synthetic model/tokenizer pair.

The shared U1 pair is deliberately cap-64.  C17's committed W-Q truncation
position is 96 content ids, so using the shared pair silently clips the very
positions this construction is meant to mutate.  This wrapper reuses the
pinned U1 generator and changes only the synthetic model context cap to 512.
Artifacts are scratch outputs, never checked in.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
BASE = HERE.parents[1] / "regenerate_tokenizer_pair_fixture.py"
SPEC = importlib.util.spec_from_file_location("te222_u1_pair_generator", BASE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load base pair generator: {BASE}")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


def generate_highcap_model(tools_dir: Path, out_path: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")
    config = pipeline.ModelConfig(
        hidden_size=32, num_hidden_layers=8, num_attention_heads=4,
        num_key_value_heads=2, head_dim=128, intermediate_size=64,
        vocab_size=base.PAIR_VOCAB_SIZE, rope_theta=10000.0,
        rms_norm_eps=1e-6, tie_word_embeddings=True, context_cap=512,
    )
    model = pipeline.fixture_model(config)
    sections, _ = convert_model.build_sections(model)
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, context_cap=512, fingerprint={fingerprint}")


if __name__ == "__main__":
    base.generate_model = generate_highcap_model
    raise SystemExit(base.main(sys.argv[1:]))
