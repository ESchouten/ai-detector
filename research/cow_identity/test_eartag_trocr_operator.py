"""Equivalent explicit/reduced/flattened linear backward on a known CPU fixture."""

import torch
from eartag_trocr_operator import isolated


def test_linear_backward_forms_preserve_full_batch_and_matrix_values():
    x = torch.arange(12, dtype=torch.float32).reshape(2, 2, 3) / 10
    w = torch.arange(15, dtype=torch.float32).reshape(5, 3) / 20
    g = torch.arange(20, dtype=torch.float32).reshape(2, 2, 5) / 7
    source = {
        "projection_input": x,
        "projection_weight": w,
        "projection_output_gradient": g,
    }
    expected = g @ w
    for kind in (
        "native3d_explicit_gradient",
        "native3d_scalar_dot",
        "flat2d_explicit_gradient",
        "manual3d_input_gradient",
        "manual2d_input_gradient",
    ):
        result = isolated("cpu", source, kind)
        torch.testing.assert_close(result["input_gradient"], expected)
        if "weight_gradient" in result:
            torch.testing.assert_close(
                result["weight_gradient"], g.reshape(-1, 5).T @ x.reshape(-1, 3)
            )
