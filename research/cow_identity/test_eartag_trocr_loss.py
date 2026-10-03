"""Correct seq2seq targets must not shift a second time or include padding."""

import pytest
import torch
from eartag_trocr_loss import aligned_loss


def test_correct_position_and_padding_gradient():
    labels = torch.tensor([[0, 3, 2, -100]])
    logits = torch.tensor(
        [[[10.0, 0, 0, 0], [0, 0, 0, 10.0], [0, 0, 10.0, 0], [0, 100.0, 0, 0]]],
        requires_grad=True,
    )
    loss = aligned_loss(logits, labels)
    assert loss < 0.001
    loss.backward()
    assert logits.grad[0, -1].tolist() == [0, 0, 0, 0]
    assert aligned_loss(logits, torch.tensor([[3, 2, -100, -100]])) > 9


def test_mismatched_target_positions_fail():
    with pytest.raises(ValueError, match="aligned"):
        aligned_loss(torch.zeros(1, 3, 4), torch.zeros(1, 2, dtype=torch.int64))
