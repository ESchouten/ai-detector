import copy

import numpy as np
import pytest
import torch
from eartag_localization_training import arguments, state_hashes, xywh
from PIL import Image


def test_native_roi_normalization_retains_clipped_edge_fragments():
    assert xywh([0, 0, 1, 20], 100, 40) == [0.005, 0.25, 0.01, 0.5]
    assert xywh([20, 10, 100, 40], 100, 40) == [0.6, 0.625, 0.8, 0.75]
    for box in ([0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, 101, 1], [0, 0, float("nan"), 1]):
        with pytest.raises(ValueError):
            xywh(box, 100, 40)


def test_native_training_transforms_do_not_drop_or_randomize_boxes(tmp_path):
    from ultralytics.cfg import get_cfg
    from ultralytics.data import YOLODataset

    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    rng = np.random.default_rng(2)
    Image.fromarray(rng.integers(0, 256, (64, 96, 3), dtype=np.uint8)).save(
        tmp_path / "images/a.png"
    )
    (tmp_path / "labels/a.txt").write_text("0 0.5 0.5 1 1\n1 0.1 0.2 0.06 0.09\n")
    args = arguments()
    dataset = YOLODataset(
        img_path=str(tmp_path / "images"),
        imgsz=128,
        batch_size=2,
        augment=True,
        hyp=get_cfg(overrides=args),
        data={"names": {0: "head", 1: "ear_tag"}, "nc": 2, "channels": 3},
    )
    first, second = dataset[0], dataset[0]
    assert first["cls"].flatten().tolist() == [0.0, 1.0]
    for key in ("img", "cls", "bboxes"):
        assert torch.equal(first[key], second[key])


def test_final_ema_comparison_detects_changed_or_quantized_state():
    model = torch.nn.Linear(3, 2)
    original = state_hashes(model)
    assert state_hashes(copy.deepcopy(model)) == original
    assert state_hashes(copy.deepcopy(model).half()) != original
    with torch.no_grad():
        model.weight[0, 0] += 0.25
    assert state_hashes(model) != original
