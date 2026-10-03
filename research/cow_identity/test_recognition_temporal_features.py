import cv2
import numpy as np
import pytest
from benchmark import digest
from cutie_features import object_crops
from recognition_temporal_features import frame_crops, positive_groups
from video_assessment import pixels_hash


def row(track, second, run=0):
    return {"track_id": track, "second": second, "run_start": run}


def test_no_untrained_unknown_or_cross_run_positives():
    rows = [row(track, second) for track in range(8) for second in (0, 20)]
    rows += [row(0, second, 100) for second in (100, 120)]
    groups = positive_groups(rows)
    assert [g["second"] for g in groups] == [0, 20]
    assert all(len(g["pairs"]) == 4 for g in groups)
    assert all(p["track_id"] < 4 for g in groups for p in g["pairs"])
    assert all(p["run_start"] == 0 for g in groups for p in g["pairs"])


def test_same_frame_negatives_only_and_embargo_excluded():
    rows = [row(0, 0), row(0, 20), row(1, 1), row(1, 21)]
    rows += [row(track, second, 400) for track in range(4) for second in (400, 420)]
    assert positive_groups(rows) == []


def test_deterministic_gap20_then_earlier_tie():
    rows = [row(track, second) for track in (0, 1) for second in (0, 10, 20, 30, 40)]
    groups = positive_groups(rows)
    middle = next(g for g in groups if g["second"] == 20)
    assert [p["positive_second"] for p in middle["pairs"]] == [0, 0]
    assert all(
        10 <= abs(p["anchor_second"] - p["positive_second"]) <= 30
        for g in groups
        for p in g["pairs"]
    )


def test_lossless_uint16_masks_keep_actual_slot_inventory(tmp_path):
    (tmp_path / "masks").mkdir()
    image = np.full((100, 100, 3), 70, np.uint8)
    mask = np.zeros((100, 100), np.uint16)
    mask[10:90, 10:90] = 1
    path = tmp_path / "masks/0.png"
    assert cv2.imwrite(str(path), mask)
    boxes, expected, _ = object_crops(image, mask)
    frame = {
        "second": 0,
        "source_pixels_sha256": pixels_hash(image),
        "mask_sha256": digest(path),
        "boxes": boxes,
        "objects": [{"track_id": 0}],
    }
    actual_boxes, actual = frame_crops(frame, image, tmp_path)
    assert actual_boxes == boxes
    np.testing.assert_array_equal(actual[0], expected[0])
    mask[1:3, 1:3] = 7
    assert cv2.imwrite(str(path), mask)
    frame["mask_sha256"] = digest(path)
    with pytest.raises(ValueError, match="Invalid indexed"):
        frame_crops(frame, image, tmp_path)
