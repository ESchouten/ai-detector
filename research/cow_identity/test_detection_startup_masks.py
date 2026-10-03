import numpy as np
from detection_startup_masks import RULES, select_masks, temporal_matches


def proposals(count):
    return [
        {"x1": 0, "y1": 0, "x2": 20, "y2": 20, "confidence": 1 - i / 10}
        for i in range(count)
    ]


def test_duplicate_masks_keep_confidence_winner_without_dropping_adjacent_cow():
    masks = np.zeros((3, 20, 20), bool)
    masks[0, :8, :8] = True
    masks[1] = masks[0]
    masks[2, 10:18, 10:18] = True
    original = masks.copy()
    result, assigned = select_masks(masks, proposals(3), RULES)
    assert result["selected"] == [0, 2]
    assert result["rows"][1]["suppressed_by"] == 0
    assert np.array_equal(masks, original)
    assert np.array_equal(assigned[2], masks[2])


def test_partial_overlap_marks_both_ambiguous_before_pixel_assignment():
    masks = np.zeros((2, 20, 20), bool)
    masks[0, :10, :10] = True
    masks[1, :10, 5:15] = True
    result, assigned = select_masks(masks, proposals(2), RULES)
    assert result["selected"] == []
    assert all(r["rejections"] == ["ambiguous_overlap"] for r in result["rows"])
    assert not assigned.any()


def test_minor_shared_boundary_uses_stable_order_without_mutating_input():
    masks = np.zeros((2, 20, 20), bool)
    masks[0, :10, :10] = True
    masks[1, :10, 9:19] = True
    result, assigned = select_masks(masks, proposals(2), RULES)
    assert result["selected"] == [0, 1]
    assert not np.any(assigned[0] & assigned[1])
    assert assigned[0].sum() == 100 and assigned[1].sum() == 90
    assert masks[1].sum() == 100


def test_ambiguous_temporal_association_never_initializes_two_ids_for_one_cow():
    old = np.zeros((1, 20, 20), bool)
    old[0, :10, :10] = True
    current = np.repeat(old, 2, axis=0)
    value = temporal_matches(old, current, [0], [0, 1], 0.5)
    assert value["matched"] == []
    assert value["unconfirmed_current"] == [0, 1]


def test_clipped_object_survives_but_mask_outside_prompt_is_rejected():
    masks = np.zeros((2, 20, 20), bool)
    masks[0, :5, :5] = True
    masks[1, 10:20, 10:20] = True
    boxes = proposals(2)
    boxes[1].update(x2=2, y2=2)
    value, _ = select_masks(masks, boxes, RULES)
    assert value["selected"] == [0]
    assert value["rows"][1]["rejections"] == ["prompt_support"]
