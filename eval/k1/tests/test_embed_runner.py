"""Tests for component 2 -- the embedding runner. These load real models from the local HF
cache and run a real forward pass; skipped automatically if CUDA or the local cache entry
is unavailable, rather than mocked, per StandardsDocument.md 5.4's real-workload rule."""
from __future__ import annotations

import os

import pytest
import torch

from eval.k1.embed_runner import (
    ModelSpec,
    POOLING_NATIVE,
    POOLING_PS1_PRE_NORM,
    POOLING_PS2_POST_NORM,
    embed_texts,
)

pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(), reason="U-K1's embedding runner is CUDA-only per the design"
)

QWEN25_0_5B_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
BGE_SMALL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QWEN3_EMB_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"

TEXTS = [
    "Cats are small mammals.",
    "Rockets reach orbit using combustion.",
    "Photosynthesis converts light to energy.",
]


def _local_cache_has(repo_id: str) -> bool:
    hf_home = os.environ.get("HF_HOME", "")
    cache_name = "models--" + repo_id.replace("/", "--")
    return hf_home and os.path.isdir(os.path.join(hf_home, "hub", cache_name))


@pytest.mark.skipif(not _local_cache_has("Qwen/Qwen2.5-0.5B-Instruct"), reason="model not cached locally")
def test_ps1_and_ps2_pooling_differ_on_a_real_forward_pass():
    """PS-1 (pre-final-norm mean) and PS-2 (post-final-norm mean) must be genuinely
    different quantities on the same real forward pass -- if they were identical, the
    forward hook capturing the norm module's input vs output would be broken."""
    spec1 = ModelSpec(
        name="qwen25-0.5b-ps1", hf_repo="Qwen/Qwen2.5-0.5B-Instruct",
        revision=QWEN25_0_5B_REVISION, pooling=POOLING_PS1_PRE_NORM, batch_size=2, max_length=64,
    )
    spec2 = ModelSpec(
        name="qwen25-0.5b-ps2", hf_repo="Qwen/Qwen2.5-0.5B-Instruct",
        revision=QWEN25_0_5B_REVISION, pooling=POOLING_PS2_POST_NORM, batch_size=2, max_length=64,
    )
    vecs1, man1 = embed_texts(spec1, TEXTS, device="cuda")
    vecs2, man2 = embed_texts(spec2, TEXTS, device="cuda")
    assert vecs1.shape == vecs2.shape == (3, 896)
    assert not (vecs1 == vecs2).all()
    assert man1.vectors_sha256 != man2.vectors_sha256


@pytest.mark.skipif(not _local_cache_has("BAAI/bge-small-en-v1.5"), reason="model not cached locally")
def test_native_pooling_auto_detects_cls_for_bge():
    spec = ModelSpec(
        name="bge-small-ref", hf_repo="BAAI/bge-small-en-v1.5", revision=BGE_SMALL_REVISION,
        pooling=POOLING_NATIVE, batch_size=2, max_length=64,
    )
    vecs, manifest = embed_texts(spec, TEXTS, device="cuda")
    assert vecs.shape == (3, 384)
    assert manifest.pooling == "native:cls"


@pytest.mark.skipif(not _local_cache_has("Qwen/Qwen3-Embedding-0.6B"), reason="model not cached locally")
def test_native_pooling_auto_detects_last_token_for_qwen3_embedding():
    spec = ModelSpec(
        name="qwen3-emb", hf_repo="Qwen/Qwen3-Embedding-0.6B", revision=QWEN3_EMB_REVISION,
        pooling=POOLING_NATIVE, batch_size=2, max_length=64,
    )
    vecs, manifest = embed_texts(spec, TEXTS, device="cuda")
    assert vecs.shape == (3, 1024)
    assert manifest.pooling == "native:last_token"


def test_unpinned_revision_refuses():
    from eval.k1.guards import K1GuardError

    spec = ModelSpec(
        name="x", hf_repo="Qwen/Qwen2.5-0.5B-Instruct", revision="main",
        pooling=POOLING_PS1_PRE_NORM,
    )
    with pytest.raises(K1GuardError) as exc:
        embed_texts(spec, TEXTS, device="cuda")
    assert exc.value.code == "K1_MODEL_UNPINNED"
