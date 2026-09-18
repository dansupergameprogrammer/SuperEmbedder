"""Mint C4's disposable cap-512 model with an all-zero final norm gain."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BASE = HERE.parent / "regenerate_c17_highcap_pair_fixture.py"
SPEC = importlib.util.spec_from_file_location("te230_c4_highcap_generator", BASE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load high-cap generator: {BASE}")
highcap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(highcap)


def generate_zero_gain_model(tools_dir: Path, out_path: Path) -> None:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")
    config = pipeline.ModelConfig(
        hidden_size=32, num_hidden_layers=8, num_attention_heads=4,
        num_key_value_heads=2, head_dim=128, intermediate_size=64,
        vocab_size=highcap.base.PAIR_VOCAB_SIZE, rope_theta=10000.0,
        rms_norm_eps=1e-6, tie_word_embeddings=True, context_cap=512,
    )
    model = pipeline.fixture_model(config)
    model.weights["final_norm.gain"].fill(0)
    sections, _ = convert_model.build_sections(model)
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, context_cap=512, final_norm.gain=all-zero, fingerprint={fingerprint}")


if __name__ == "__main__":
    highcap.base.generate_model = generate_zero_gain_model
    raise SystemExit(highcap.base.main(sys.argv[1:]))
