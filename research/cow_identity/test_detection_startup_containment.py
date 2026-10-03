import numpy as np
from detection_startup_containment import containment_selection
from detection_startup_masks import RULES, select_masks


def proposals(count):
    return [
        {"x1": 0, "y1": 0, "x2": 20, "y2": 20, "confidence": 1 - i / 10}
        for i in range(count)
    ]


def test_contained_fragment_yields_to_fuller_mask_even_with_higher_confidence():
    masks = np.zeros((2, 20, 20), bool)
    masks[0, :10, :6] = True
    masks[1, :10, :10] = True
    original = masks.copy()
    decision, pixels = containment_selection(masks, proposals(2))
    assert decision["selected"] == [1]
    assert decision["rows"][0]["suppressed_by"] == 1
    assert np.array_equal(pixels[1], masks[1])
    assert np.array_equal(original, masks)


def test_parent_with_disjoint_children_abstains_including_head_plus_torso_case():
    masks = np.zeros((3, 20, 20), bool)
    masks[0, :10, :20] = True
    masks[1, :10, :6] = True
    masks[2, :10, 8:20] = True
    decision, pixels = containment_selection(masks, proposals(3))
    assert decision["selected"] == []
    assert len(decision["guarded_groups"]) == 1
    assert all(
        "multi_part_parent_ambiguity" in row["rejections"] for row in decision["rows"]
    )
    assert not pixels.any()


def test_uncontained_overlap_stays_ambiguous_and_disjoint_neighbor_is_preserved():
    masks = np.zeros((3, 20, 20), bool)
    masks[0, :10, :10] = True
    masks[1, :10, 5:15] = True
    masks[2, 12:20, 12:20] = True
    decision, _ = containment_selection(masks, proposals(3))
    assert decision["selected"] == [2]
    assert all("ambiguous_overlap" in row["rejections"] for row in decision["rows"][:2])


def test_original_near_identical_confidence_nms_is_not_replaced_by_area_order():
    masks = np.zeros((2, 20, 20), bool)
    masks[0, :10, :9] = True
    masks[1, :10, :10] = True
    original, expected = select_masks(masks, proposals(2), RULES)
    decision, actual = containment_selection(masks, proposals(2))
    assert decision["selected"] == original["selected"] == [0]
    assert decision["rows"][1]["rejections"] == ["duplicate_mask"]
    assert np.array_equal(actual, expected)
