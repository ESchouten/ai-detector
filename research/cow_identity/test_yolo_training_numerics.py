import torch
from yolo_training_numerics import compare, flatten


def test_native_output_leaves_and_missing_zero_gradients_remain_explicit():
    leaves = flatten({"boxes": torch.ones(2, 4), "feats": [torch.zeros(2, 3, 4, 4)]})
    assert set(leaves) == {".boxes", ".feats.0"}
    assert compare(None, None) == {
        "missing_cpu": True,
        "missing_mps": True,
        "both_missing": True,
    }
    assert not compare(None, torch.ones(1))["both_missing"]
    assert compare(torch.zeros(2), torch.ones(2))["relative_l2"] is None
    assert compare(torch.ones(2), torch.tensor([float("nan"), 1.0]))["finite"] is False
    assert compare(torch.ones(2), torch.ones(2))["exact"]
