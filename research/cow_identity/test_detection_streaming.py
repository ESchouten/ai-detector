import copy
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from detection_quarantine_recovery import CorroboratedRecovery
from detection_streaming import (
    decide_frame,
    model_metadata,
    source_frames,
    validate_cadence,
)
from video_assessment import pixels_hash


def policy():
    rules = json.loads(
        Path(__file__)
        .with_name("detection_cutie_quarantine_v2_protocol.json")
        .read_text()
    )
    return CorroboratedRecovery(
        rules,
        range(1, 4),
        {
            "minimum_iou": 0.5,
            "minimum_p10": 0.7,
            "donor_area_ratio": 0.5,
            "consecutive_frames": 3,
        },
    )


def test_same_frame_policy_preserves_anonymous_slots_and_real_detector_scores():
    mask = np.zeros((20, 40), dtype=np.uint8)
    mask[2:15, 2:11], mask[2:15, 15:24], mask[2:15, 28:37] = 1, 2, 3
    objects = [
        {"track_id": 0, "p10_probability": 0.9},
        {"track_id": 1, "p10_probability": 0.6},
        {"track_id": 2, "p10_probability": 0.95},
    ]
    proposals = [
        dict(x1=x, y1=2, x2=x + 8, y2=14, confidence=score)
        for x, score in ((2, 0.82), (15, 0.88), (28, 0.91))
    ]
    result = decide_frame(
        0,
        mask,
        objects,
        proposals,
        policy(),
        {1, 2},
        {"minimum_iou": 0.5, "minimum_p10": 0.7},
    )
    assert result["named_track_ids"] == [0]
    assert [box["track_id"] for box in result["boxes"]] == [0, 1, 2]
    assert [box["confidence"] for box in result["boxes"]] == [0.82, 0.88, 0.91]
    assert result["objects"] == objects
    missing = decide_frame(
        0,
        mask,
        objects,
        [],
        policy(),
        {1, 2},
        {"minimum_iou": 0.5, "minimum_p10": 0.7},
    )
    assert missing["named_track_ids"] == []
    assert len(missing["boxes"]) == 3
    assert all(box["confidence"] is None for box in missing["boxes"])


def test_source_manifest_rejects_gaps_repeated_samples_and_wrong_original_indices():
    clip = {
        "source_fps": 20,
        "rows": [
            {"second": 0, "publisher_frame": 1},
            {"second": 0.5, "publisher_frame": 11},
            {"second": 1, "publisher_frame": 21},
        ],
    }
    protocol = {"processing_fps": 2, "last_processed_second": 1}
    validate_cadence(clip, protocol)
    for change in ("missing", "duplicate", "shifted"):
        broken = copy.deepcopy(clip)
        if change == "missing":
            broken["rows"].pop(1)
        elif change == "duplicate":
            broken["rows"][1] = broken["rows"][0]
        else:
            broken["rows"][1]["publisher_frame"] += 1
        with pytest.raises(ValueError):
            validate_cadence(broken, protocol)


def test_one_decoded_source_is_verified_before_either_model_can_use_it(tmp_path):
    path = tmp_path / "sampled.avi"
    frames = [np.full((16, 24, 3), value, np.uint8) for value in (30, 60, 90)]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), 2, (24, 16))
    assert writer.isOpened()
    for image in frames:
        writer.write(image)
    writer.release()
    rows = [
        {"second": i / 2, "pixels_sha256": pixels_hash(image)}
        for i, image in enumerate(frames)
    ]
    capture = cv2.VideoCapture(str(path))
    try:
        decoded = list(source_frames(capture, rows))
        for (source, image), row, expected in zip(decoded, rows, frames, strict=True):
            assert source == row
            np.testing.assert_array_equal(image, expected)
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        rows[1]["pixels_sha256"] = "0" * 64
        iterator = source_frames(capture, rows)
        next(iterator)
        with pytest.raises(ValueError, match="Decoded source pixels"):
            next(iterator)
    finally:
        capture.release()


def test_sdk_device_spellings_both_mean_metal_but_cpu_fallback_is_rejected(monkeypatch):
    import torch

    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    parameter = SimpleNamespace(device=torch.device("mps:0"), dtype=torch.float32)
    core = SimpleNamespace(
        network=SimpleNamespace(parameters=lambda: iter([parameter]))
    )
    backend = SimpleNamespace(device=torch.device("mps"), fp16=True)
    detector = SimpleNamespace(
        predictor=SimpleNamespace(
            model=backend,
            args=SimpleNamespace(
                imgsz=640,
                rect=True,
                batch=1,
                quantize=16,
                conf=0.4,
                iou=0.7,
                max_det=300,
            ),
        ),
        names={0: "cow"},
    )
    assert model_metadata(core, detector)["yolo_device"] == "mps"
    backend.device = torch.device("mps:0")
    assert model_metadata(core, detector)["yolo_device"] == "mps:0"
    backend.device = torch.device("cpu")
    with pytest.raises(ValueError, match="corroborator must execute"):
        model_metadata(core, detector)
