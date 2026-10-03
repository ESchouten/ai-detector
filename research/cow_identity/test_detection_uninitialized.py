"""Unknown exposure denominators and noncontiguous Cutie object-channel mapping."""

import numpy as np
import pytest
from cutie_object_state import stable_mask_diagnostics
from detection_sam_tracking import score
from detection_uninitialized import derive_masks


def test_probability_channels_follow_compaction_not_stable_id():
    mask = np.zeros((10, 20), np.int64)
    mask[1:5, 1:5], mask[1:5, 10:15] = 7, 42
    probabilities = np.zeros((3, 10, 20), np.float32)
    probabilities[1], probabilities[2] = 0.8, 0.95
    before = stable_mask_diagnostics(mask, probabilities, {7: 1, 42: 2})
    assert [row["track_id"] for row in before] == [6, 41]
    mask[mask == 7] = 0
    after = stable_mask_diagnostics(mask, probabilities[[0, 2]], {42: 1})
    assert after == [before[1]]
    with pytest.raises(ValueError, match="no current"):
        stable_mask_diagnostics(mask, probabilities[[0, 2]], {42: 2})
    with pytest.raises(ValueError, match="share"):
        stable_mask_diagnostics(mask, probabilities, {7: 1, 42: 1})


def test_removing_anonymous_seeds_preserves_every_named_pixel():
    masks = np.zeros((8, 10, 20), bool)
    for i in range(8):
        masks[i, 1:8, i * 2 : i * 2 + 3] = True
    selected = derive_masks(masks)
    assert selected.shape == (6, 10, 20)
    np.testing.assert_array_equal(selected, masks[:6])


def test_unseeded_unknowns_stay_in_scorer_denominator_and_wrong_name_count():
    records = {
        "frame_id": np.array([1, 1, 1]),
        "cow_id": np.array([1, 7, 8]),
        "x_center": np.array([0.15, 0.5, 0.85]),
        "y_center": np.array([0.5] * 3),
        "width": np.array([0.2] * 3),
        "height": np.array([0.4] * 3),
    }
    value = {
        "timeline": [
            {
                "second": 0,
                "boxes": [
                    {
                        "x1": 40,
                        "y1": 30,
                        "x2": 60,
                        "y2": 70,
                        "label": "cow",
                        "track_id": 0,
                    }
                ],
            }
        ]
    }
    result = score(
        value,
        records,
        {"source_fps": 20, "width": 100, "height": 100},
        {
            "last_processed_second": 0,
            "score_seconds": [0, 0],
            "named_cows": list(range(1, 7)),
        },
        [{"cow": i} for i in range(1, 7)],
    )
    counts = result["naming_counts"]
    assert counts["visible_annotations"] == 3
    assert counts["visible_known"] == 1
    assert counts["visible_unknown"] == 2
    assert counts["unknown_named"] == 1
    assert counts["correct_name"] == 0
