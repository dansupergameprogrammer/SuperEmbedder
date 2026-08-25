"""Pooling variants for component 2, the embedding runner.

Design reference: te33-k1-gate-design-2026-08-25.md Section 6.2 row 2 ("PS-1 mean pooling
over positions 1..n-1 for the decoder candidates (plan Section 3.2), model-native pooling
for the reference") and Section 1 / Section 9.1 ("both Q-A1 pooling variants ... PS-1 vs
PS-2" -- PS-1 is pre-final-norm mean pooling, PS-2 is post-final-norm mean pooling, the two
variants the plan's Q-A1 leg compares).

All pooling assumes RIGHT-padding (this instrument's tokenizer calls always pad right --
see embed_runner.py), so column index 0 is position 0 (the first real token, typically BOS)
for every row with no left-padding shift, and the last real token of row ``i`` is at column
``attention_mask[i].sum() - 1``.
"""
from __future__ import annotations

from typing import Dict, Optional

import torch


def mean_pool_excluding_position_zero(hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """PS-1 / PS-2's pooling rule: mean over positions 1..n-1 (design line: "PS-1 mean
    pooling over positions 1..n-1"), excluding position 0 and excluding padding. ``hidden``
    is ``[batch, seq, hidden]``; the two pooling variants differ in WHICH hidden tensor is
    passed in (pre- vs post-final-norm), not in this function."""
    mask = attention_mask.clone()
    mask[:, 0] = 0  # exclude position 0
    mask = mask.unsqueeze(-1).to(hidden.dtype)  # [batch, seq, 1]
    summed = (hidden * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1.0)
    return summed / counts


def cls_pool(hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Native CLS-token pooling (e.g. bge-small-en-v1.5's declared
    ``pooling_mode_cls_token``): position 0 of every row."""
    return hidden[:, 0, :]


def last_token_pool(hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Native last-token pooling (e.g. Qwen3-Embedding-0.6B's declared
    ``pooling_mode_lasttoken``): the last real (non-padding) token of each row, under
    right-padding."""
    lengths = attention_mask.sum(dim=1) - 1  # [batch]
    idx = lengths.clamp(min=0).long()
    batch_idx = torch.arange(hidden.size(0), device=hidden.device)
    return hidden[batch_idx, idx, :]


def read_native_pooling_mode(model_snapshot_dir: str) -> Optional[str]:
    """Reads a sentence-transformers-formatted model's ``1_Pooling/config.json`` to
    determine its declared native pooling mode. Returns ``"cls"``, ``"mean"``,
    ``"last_token"``, or ``None`` if no such config exists (a plain decoder checkpoint with
    no sentence-transformers wrapper -- e.g. the Qwen2.5-Instruct candidates)."""
    import json
    from pathlib import Path

    config_path = Path(model_snapshot_dir) / "1_Pooling" / "config.json"
    if not config_path.exists():
        return None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("pooling_mode_cls_token"):
        return "cls"
    if config.get("pooling_mode_lasttoken"):
        return "last_token"
    if config.get("pooling_mode_mean_tokens"):
        return "mean"
    return None


NATIVE_POOLING_FUNCS = {
    "cls": cls_pool,
    "last_token": last_token_pool,
}
