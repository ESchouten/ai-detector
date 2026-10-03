"""Numerical diagnostics must expose different/absent gradients explicitly."""

import pytest
import torch
from eartag_trocr_backward import compare_runs, compare_tensor, norm_on_cpu


def test_gradient_norm_matches_known_vector_including_missing_gradients():
    assert norm_on_cpu({"a": torch.tensor([3.0, 4.0]), "unused": None}) == 5
    result = compare_tensor(torch.tensor([3.0, 4.0]), torch.tensor([3.0, 5.0]))
    assert result["maximum_absolute_difference"] == 1
    assert result["relative_l2_difference"] == 0.2
    assert not result["exact"]


def test_gradient_presence_change_is_not_hidden_as_zero():
    a = {
        "initial": {"p": torch.ones(1)},
        "gradients": {"p": None},
        "updates": {"p": torch.zeros(1)},
        "logits": [],
    }
    b = {**a, "gradients": {"p": torch.zeros(1)}}
    with pytest.raises(ValueError, match="presence"):
        compare_runs(a, b)


def test_nonfinite_gradients_fail_diagnostic():
    with pytest.raises(ValueError, match="finite"):
        compare_tensor(torch.ones(1), torch.tensor([float("nan")]))
