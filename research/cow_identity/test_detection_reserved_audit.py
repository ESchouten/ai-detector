"""The error-review renderer must preserve emitted geometry, not confidence."""

import cv2
import numpy as np
import pytest
from benchmark import digest
from detection_cutie import boxes_from_mask
from detection_reserved_audit import checked_mask


def saved_mask(tmp_path, monkeypatch):
    monkeypatch.setattr("detection_reserved_audit.RUN", tmp_path)
    directory = tmp_path / "masks"
    directory.mkdir()
    mask = np.zeros((12, 16), np.uint8)
    mask[2:10, 3:12] = 1
    path = directory / "1800.png"
    cv2.imwrite(str(path), mask)
    boxes = boxes_from_mask(mask)
    boxes[0]["confidence"] = 0.72
    return (
        path,
        mask,
        {
            "second": 1800,
            "mask_sha256": digest(path),
            "boxes": boxes,
        },
    )


def test_review_preserves_geometry_with_independent_detector_confidence(
    tmp_path, monkeypatch
):
    _, expected, frame = saved_mask(tmp_path, monkeypatch)
    actual, components = checked_mask(frame, expected.shape)
    np.testing.assert_array_equal(actual, expected)
    assert components[0]["retained_area"] == 72


def test_review_rejects_changed_pixels(tmp_path, monkeypatch):
    path, mask, frame = saved_mask(tmp_path, monkeypatch)
    mask[0, 0] = 1
    cv2.imwrite(str(path), mask)
    with pytest.raises(ValueError, match="differs from the recorded"):
        checked_mask(frame, mask.shape)


def test_review_rejects_changed_emitted_geometry(tmp_path, monkeypatch):
    _, mask, frame = saved_mask(tmp_path, monkeypatch)
    frame["boxes"][0]["x2"] += 1
    with pytest.raises(ValueError, match="emitted geometry"):
        checked_mask(frame, mask.shape)
