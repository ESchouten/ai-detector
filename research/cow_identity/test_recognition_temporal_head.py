import numpy as np
import pytest
import torch
from recognition_temporal_head import (
    ResidualMetricHead,
    batch_loss,
    diverse_bank,
    frame_loss,
    indexed_groups,
)


def test_zero_initialized_residual_preserves_finite_base_and_can_learn():
    torch.set_num_threads(2)
    torch.manual_seed(42)
    head = ResidualMetricHead()
    vectors = torch.nn.functional.normalize(torch.randn(8, 2152), dim=1)
    assert torch.allclose(head(vectors), vectors, atol=1e-6)
    loss = batch_loss(head, vectors, [([0, 1], [2, 3]), ([4, 5], [6, 7])])
    loss.backward()
    assert torch.isfinite(loss)
    assert head.output.weight.grad.abs().sum() > 0


def test_frame_loss_uses_only_temporal_positive_and_other_same_frame_anchors():
    anchors = torch.eye(3)
    positive = anchors.clone()
    loss = frame_loss(anchors, positive)
    expected = np.log(1 + 2 * np.exp(-10))
    np.testing.assert_allclose(loss.numpy(), expected, rtol=1e-3)
    # Different frame composition has no implicit shared batch negatives.
    assert frame_loss(anchors[:2], positive[:2]).shape == (2,)


def test_indexing_rejects_unknown_untrained_and_calibration_rows():
    manifest = {
        "rows": [
            {"kind": "observation", "second": second, "track_id": track}
            for second in (0, 20, 450)
            for track in range(8)
        ]
    }
    pairs = [
        {"track_id": track, "anchor_second": 0, "positive_second": 20}
        for track in (0, 1)
    ]
    protocol = {"training_groups": [{"second": 0, "pairs": pairs}]}
    assert indexed_groups(protocol, manifest) == [([0, 1], [8, 9])]
    pairs[0]["track_id"] = 6
    with pytest.raises(ValueError, match="Non-training"):
        indexed_groups(protocol, manifest)
    pairs[0]["track_id"] = 0
    pairs[0]["positive_second"] = 450
    with pytest.raises(ValueError, match="Non-training"):
        indexed_groups(protocol, manifest)


def test_dense_bank_preserves_only_early_quality_known_slots_and_fixed_budget():
    rows = [
        {"kind": "observation", "second": second, "track_id": track}
        for second in (0, 1, 420)
        for track in range(8)
    ]
    values = np.eye(len(rows), dtype=np.float32)
    selected = diverse_bank({"rows": rows}, values, rows, maximum=1)
    assert selected == list(range(6))  # All ties use chronological order.
    assert all(rows[i]["second"] <= 419 and rows[i]["track_id"] < 6 for i in selected)
