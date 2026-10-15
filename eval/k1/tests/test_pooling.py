"""Tests for pooling.py -- pure tensor operations, no model load required."""
from __future__ import annotations

import pytest

# TE-43: skip, rather than error at collection, where torch is not installed.
torch = pytest.importorskip("torch", reason="pooling cells need torch")

from eval.k1.pooling import cls_pool, last_token_pool, mean_pool_excluding_position_zero


def test_mean_pool_excludes_position_zero_and_padding():
    # batch of 1, seq len 4, hidden dim 2. Position 0 = [100, 100] (must be excluded).
    # Real tokens at positions 1,2 = [1,1] and [3,3]; position 3 is padding [999,999].
    hidden = torch.tensor([[[100.0, 100.0], [1.0, 1.0], [3.0, 3.0], [999.0, 999.0]]])
    attention_mask = torch.tensor([[1, 1, 1, 0]])
    pooled = mean_pool_excluding_position_zero(hidden, attention_mask)
    assert torch.allclose(pooled, torch.tensor([[2.0, 2.0]]))  # mean of [1,1] and [3,3]


def test_mean_pool_batch_with_different_real_lengths():
    hidden = torch.tensor([
        [[9.0, 9.0], [1.0, 0.0], [3.0, 0.0], [0.0, 0.0]],  # real length 3 (pos 1,2 count)
        [[9.0, 9.0], [2.0, 0.0], [0.0, 0.0], [0.0, 0.0]],  # real length 2 (pos 1 counts)
    ])
    attention_mask = torch.tensor([[1, 1, 1, 0], [1, 1, 0, 0]])
    pooled = mean_pool_excluding_position_zero(hidden, attention_mask)
    assert torch.allclose(pooled[0], torch.tensor([2.0, 0.0]))  # mean(1,3)
    assert torch.allclose(pooled[1], torch.tensor([2.0, 0.0]))  # just position 1


def test_cls_pool_takes_position_zero():
    hidden = torch.tensor([[[5.0, 5.0], [1.0, 1.0]]])
    attention_mask = torch.tensor([[1, 1]])
    pooled = cls_pool(hidden, attention_mask)
    assert torch.allclose(pooled, torch.tensor([[5.0, 5.0]]))


def test_last_token_pool_finds_last_real_token_under_right_padding():
    hidden = torch.tensor([
        [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [999.0, 999.0]],  # real length 3, last=pos2
        [[0.0, 0.0], [7.0, 7.0], [999.0, 999.0], [999.0, 999.0]],  # real length 2, last=pos1
    ])
    attention_mask = torch.tensor([[1, 1, 1, 0], [1, 1, 0, 0]])
    pooled = last_token_pool(hidden, attention_mask)
    assert torch.allclose(pooled[0], torch.tensor([2.0, 2.0]))
    assert torch.allclose(pooled[1], torch.tensor([7.0, 7.0]))
