import pytest
import torch
from recognition_spatial_tail_model import (
    TAIL_PREFIXES,
    contrastive_loss,
    normalized_tail,
    split_model,
    trainable_tail,
    validate_training_rows,
)
from recognition_temporal_head import frame_loss

from aidetector.adapters.inference.miewid import MiewidNetwork


def test_exact_tail_split_and_gradient_boundary_with_frozen_normalization():
    torch.set_num_threads(2)
    torch.manual_seed(42)
    model = MiewidNetwork().eval()
    prefix, tail = split_model(model)
    values = torch.randn(2, 3, 64, 64)
    with torch.inference_mode():
        expected = torch.nn.functional.normalize(model(values), dim=1)
        actual = normalized_tail(tail, prefix(values))
    torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-6)
    _, tail, names = trainable_tail(model)
    assert all(name.startswith(TAIL_PREFIXES) for name in names)
    before = {name: value.clone() for name, value in model.named_buffers()}
    maps = torch.randn(4, 328, 2, 2)
    with torch.no_grad():
        base = normalized_tail(tail, maps).clone()
    loss = contrastive_loss(normalized_tail(tail, maps), base, 2)
    loss.backward()
    assert any(
        p.grad is not None and p.grad.abs().sum() > 0 for p in model.parameters()
    )
    assert all(
        p.grad is None for name, p in model.named_parameters() if name not in names
    )
    assert all(
        not layer.training and all(not p.requires_grad for p in layer.parameters())
        for layer in model.modules()
        if isinstance(layer, torch.nn.modules.batchnorm._BatchNorm)
    )
    assert not model.backbone.global_pool.p.requires_grad
    assert all(
        torch.equal(value, before[name]) for name, value in model.named_buffers()
    )


def test_spatial_loss_matches_preceding_fixed_sameframe_objective():
    values = torch.nn.functional.normalize(torch.randn(8, 32), dim=1)
    expected = frame_loss(values[:4], values[4:]).mean()
    torch.testing.assert_close(contrastive_loss(values, values, 4), expected)


def test_training_boundary_excludes_unknowns_calibration_and_noncontemporary_negatives():
    rows = [
        {"kind": "observation", "track_id": track, "second": second}
        for second in (0, 20)
        for track in (0, 5)
    ]
    validate_training_rows(rows)
    for key, value in (("track_id", 6), ("second", 450), ("kind", "gallery")):
        changed = [dict(row) for row in rows]
        changed[0][key] = value
        with pytest.raises(ValueError):
            validate_training_rows(changed)
    rows[1]["second"] = 1
    with pytest.raises(ValueError, match="same frame"):
        validate_training_rows(rows)
