"""Component 2 -- the embedding runner.

Design reference: te33-k1-gate-design-2026-08-25.md Section 6.2 row 2, Section 7.1, Section
4.5 (query convention, TE-49 amendment).

Batched bf16 forward, ``local_files_only=True`` (design: candidates and the reference are
already resident in ``D:\\hf_cache``, no download is required for a real run). BEIR document
text is ``title + " " + text`` (the standard convention); query text is the query's own
text, optionally prefixed by a model-native instruction prompt.

**Query convention (design Section 4.5, TE-49 amendment, D-SLM5389).** Every model is queried
under its own documented query-side instruction, when one exists; a model with none is
queried bare. ``ModelSpec.query_prompt`` carries that instruction (``None`` means bare, by
that model's own documentation -- not a default applied uniformly regardless of what each
model documents). The convention actually used is recorded on the emitted manifest as
``query_convention`` (the prompt text, or the literal string ``"bare"``). **This module
always records it** -- TE-53 review, J-5 (Minor): ``guards.check_query_convention_recorded``
no longer lives here (TE-51 review, H-5 moved it to ``runner.run_gate``'s packet-assembly
point, the one place a query embedding's convention can genuinely arrive unrecorded -- the
candidate-reuse path, not this module's own embed call). A reader asking what refuses an
unrecorded convention should look there, per Section 6.2 row 2's refusal condition.

Emits vectors plus a run manifest carrying model revision, dtype, batch size, max_length,
torch/transformers versions, GPU name, a SHA-256 over the emitted vectors, and
``query_convention`` -- the fields design Section 6.2 row 2 names.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from eval.k1.guards import check_unpinned_revision
from eval.k1.pooling import (
    NATIVE_POOLING_FUNCS,
    mean_pool_excluding_position_zero,
    read_native_pooling_mode,
)

POOLING_PS1_PRE_NORM = "ps1_pre_norm_mean"
POOLING_PS2_POST_NORM = "ps2_post_norm_mean"
POOLING_NATIVE = "native"

BARE_QUERY_CONVENTION = "bare"  # recorded when a model has no documented query-side instruction


@dataclass
class ModelSpec:
    name: str  # display id, e.g. "qwen2.5-1.5b-instruct-ps1"
    hf_repo: str
    revision: str
    pooling: str  # POOLING_PS1_PRE_NORM | POOLING_PS2_POST_NORM | POOLING_NATIVE
    dtype: str = "bfloat16"
    max_length: int = 512
    batch_size: int = 4
    query_prompt: Optional[str] = None  # model-native instruction, prepended to queries only
    # TE-50 (D-SLM5390's re-run): a directory laid out like a run's own
    # `run_files/<run_id>/<set_name>/<model_name>.trec` -- when set, `runner.run_gate` reads
    # this model's ranking for a given set from `<dir>/<set_name>/<name>.trec` instead of
    # embedding and ranking it. Reuses an already-computed, already-costed candidate ranking
    # (the ticket brief's explicit instruction: "reuse Run 1's persisted candidate rankings;
    # do not re-embed the candidate") without adding a second orchestration code path.
    reuse_trec_run_dir: Optional[str] = None


@dataclass
class EmbedManifest:
    model_name: str
    hf_repo: str
    revision: str
    pooling: str
    dtype: str
    batch_size: int
    max_length: int
    torch_version: str
    transformers_version: str
    gpu_name: Optional[str]
    n_items: int
    vector_dim: int
    vectors_sha256: str
    query_convention: Optional[str] = None  # design Section 4.5; None for a document (non-query) embedding


def _beir_doc_text(row: dict) -> str:
    title = (row.get("title") or "").strip()
    text = (row.get("text") or "").strip()
    return f"{title} {text}".strip() if title else text


def _vectors_sha256(vecs: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(vecs).tobytes()).hexdigest()


def _resolve_dtype(name: str) -> torch.dtype:
    return {"bfloat16": torch.bfloat16, "float32": torch.float32, "float16": torch.float16}[name]


def embed_texts(
    model_spec: ModelSpec,
    texts: Sequence[str],
    device: str = "cuda",
    is_query: bool = False,
) -> Tuple[np.ndarray, EmbedManifest]:
    """Embeds ``texts`` (already the fully-assembled document or query strings -- callers
    apply ``_beir_doc_text`` for documents and the query prompt for queries) with
    ``model_spec``'s pooling rule. Returns ``(vectors [n, dim] float32, manifest)``.
    """
    import transformers
    from transformers import AutoModel, AutoTokenizer

    check_unpinned_revision(model_spec.hf_repo, model_spec.revision)

    # TE-51 review, H-5: this used to call ``check_query_convention_recorded`` immediately
    # after computing ``query_convention`` from this exact expression -- a guard placed one
    # line after the assignment that makes its own refusal condition unreachable (the
    # expression is truthy for every value of ``query_prompt``, so the guard fired on 0 of 4
    # reachable inputs). The check now lives in ``runner.py``, at the point a model's
    # ``query_manifest`` is folded into the packet -- the one place a query embedding's
    # convention can genuinely arrive unrecorded (the candidate-reuse path, TE-50), which is
    # exactly the failure this guard exists to catch.
    query_convention: Optional[str] = None
    if is_query:
        query_convention = model_spec.query_prompt if model_spec.query_prompt else BARE_QUERY_CONVENTION
        if model_spec.query_prompt:
            texts = [f"{model_spec.query_prompt}{t}" for t in texts]

    tokenizer = AutoTokenizer.from_pretrained(
        model_spec.hf_repo, revision=model_spec.revision, local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"  # required by every pooling function in pooling.py

    model = AutoModel.from_pretrained(
        model_spec.hf_repo,
        revision=model_spec.revision,
        local_files_only=True,
        torch_dtype=_resolve_dtype(model_spec.dtype),
    )
    model.to(device)
    model.eval()

    native_mode = None
    if model_spec.pooling == POOLING_NATIVE:
        # AutoModel.from_pretrained resolves the repo to a local snapshot directory under
        # HF_HOME; recover that directory's path to read its sentence-transformers
        # 1_Pooling/config.json (pooling.read_native_pooling_mode).
        from huggingface_hub import try_to_load_from_cache
        import os as _os

        cached_file = try_to_load_from_cache(
            model_spec.hf_repo, "1_Pooling/config.json", revision=model_spec.revision
        )
        if cached_file and cached_file != "_CACHED_NO_EXIST":
            native_mode = read_native_pooling_mode(_os.path.dirname(_os.path.dirname(cached_file)))

    all_vectors = []
    norm_hook_state: Dict[str, torch.Tensor] = {}
    hook_handle = None
    if model_spec.pooling in (POOLING_PS1_PRE_NORM, POOLING_PS2_POST_NORM):
        base = model
        norm_module = getattr(base, "norm", None)
        if norm_module is None and hasattr(base, "model"):
            norm_module = getattr(base.model, "norm", None)
        if norm_module is None:
            raise RuntimeError(
                f"model {model_spec.hf_repo} has no discoverable final-norm module for "
                f"PS-1/PS-2 pooling"
            )

        def _hook(_module, inputs, output):
            norm_hook_state["pre"] = inputs[0]
            norm_hook_state["post"] = output

        hook_handle = norm_module.register_forward_hook(_hook)

    try:
        for start in range(0, len(texts), model_spec.batch_size):
            batch_texts = list(texts[start : start + model_spec.batch_size])
            encoded = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=model_spec.max_length,
                return_tensors="pt",
            ).to(device)
            with torch.no_grad():
                outputs = model(**encoded)

            if model_spec.pooling == POOLING_PS1_PRE_NORM:
                hidden = norm_hook_state["pre"]
                pooled = mean_pool_excluding_position_zero(hidden, encoded["attention_mask"])
            elif model_spec.pooling == POOLING_PS2_POST_NORM:
                hidden = norm_hook_state["post"]
                pooled = mean_pool_excluding_position_zero(hidden, encoded["attention_mask"])
            else:  # native
                hidden = outputs.last_hidden_state
                fn = NATIVE_POOLING_FUNCS.get(native_mode, mean_pool_excluding_position_zero)
                pooled = fn(hidden, encoded["attention_mask"])

            all_vectors.append(pooled.float().cpu().numpy())
    finally:
        if hook_handle is not None:
            hook_handle.remove()

    vectors = np.concatenate(all_vectors, axis=0) if all_vectors else np.zeros((0, 0), dtype=np.float32)

    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() and device == "cuda" else None
    manifest = EmbedManifest(
        model_name=model_spec.name,
        hf_repo=model_spec.hf_repo,
        revision=model_spec.revision,
        pooling=model_spec.pooling if native_mode is None else f"{model_spec.pooling}:{native_mode}",
        dtype=model_spec.dtype,
        batch_size=model_spec.batch_size,
        max_length=model_spec.max_length,
        torch_version=torch.__version__,
        transformers_version=transformers.__version__,
        gpu_name=gpu_name,
        n_items=len(texts),
        vector_dim=int(vectors.shape[1]) if vectors.size else 0,
        vectors_sha256=_vectors_sha256(vectors),
        query_convention=query_convention,
    )
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return vectors, manifest


def embed_corpus(model_spec: ModelSpec, corpus: Sequence[dict], device: str = "cuda") -> Tuple[np.ndarray, List[str], EmbedManifest]:
    texts = [_beir_doc_text(row) for row in corpus]
    ids = [row["_id"] for row in corpus]
    vectors, manifest = embed_texts(model_spec, texts, device=device, is_query=False)
    return vectors, ids, manifest


def embed_queries(model_spec: ModelSpec, queries: Sequence[dict], device: str = "cuda") -> Tuple[np.ndarray, List[str], EmbedManifest]:
    texts = [row["text"] for row in queries]
    ids = [row["_id"] for row in queries]
    vectors, manifest = embed_texts(model_spec, texts, device=device, is_query=True)
    return vectors, ids, manifest
