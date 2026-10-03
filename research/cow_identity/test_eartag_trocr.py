"""Behavior checks for the fixed data/optimization boundary, no model weights."""

import pytest
import torch
from eartag_trocr import encode_labels, epoch_indices, optimizer_groups


class Tokenizer:
    def __call__(self, texts, **kwargs):
        assert texts == ["0024", "8.1"]
        assert kwargs["truncation"] is False
        return type(
            "Tokens",
            (),
            {
                "input_ids": torch.tensor([[0, 9, 9, 2], [0, 8, 2, 1]]),
                "attention_mask": torch.tensor([[1, 1, 1, 1], [1, 1, 1, 0]]),
            },
        )()


def test_labels_preserve_literal_input_and_only_mask_padding():
    assert encode_labels(Tokenizer(), ["0024", "8.1"]).tolist() == [
        [0, 9, 9, 2],
        [0, 8, 2, -100],
    ]


def test_partial_optimizer_tail_never_drops_training_examples():
    order = epoch_indices(19, 12, 0)
    groups = optimizer_groups(order, 4, 2)
    assert [len(group) for group in groups] == [2, 2, 1]
    assert [item for group in groups for batch in group for item in batch] == order
    assert sorted(order) == list(range(19))
    assert epoch_indices(19, 12, 0) == order
    assert epoch_indices(19, 12, 1) != order


def test_token_budget_fails_instead_of_truncating():
    class TooLong:
        def __call__(self, *_args, **_kwargs):
            return type(
                "Tokens",
                (),
                {"input_ids": torch.ones(1, 33), "attention_mask": torch.ones(1, 33)},
            )()

    with pytest.raises(ValueError, match="token budget"):
        encode_labels(TooLong(), ["no silent truncation"])
