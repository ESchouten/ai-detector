"""Seed coverage counts distinct matched animals, not the number of proposals."""

import numpy as np
from detection_initial_masks import compare_masks
from detection_initialization import seed_metrics

from aidetector.domain.models import BoundingBox


def test_duplicate_proposals_do_not_inflate_known_coverage():
    truth = [
        {"cow": 1, "box": [0, 0, 10, 10]},
        {"cow": 2, "box": [20, 0, 30, 10]},
        {"cow": 8, "box": [40, 0, 50, 10]},
    ]
    boxes = [BoundingBox(*truth[index]["box"]) for index in (0, 0, 2)]
    result = seed_metrics(boxes, truth, [1, 2])
    assert result["matched_proposals"] == 2
    assert result["false_proposals"] == 1
    assert result["correctly_seedable_known_ids"] == [1]
    assert result["missing_known_ids"] == [2]
    assert result["visible_known_coverage_ceiling"] == 0.5
    assert result["seed_recall"] == 2 / 3


def test_no_proposals_have_zero_initialization_coverage():
    result = seed_metrics([], [{"cow": 1, "box": [0, 0, 10, 10]}], [1])
    assert result["seed_precision"] == 0
    assert result["visible_known_coverage_ceiling"] == 0
    assert result["missing_known_ids"] == [1]


def test_disappearing_mask_slot_is_not_renumbered_as_another_cow():
    original = np.zeros((3, 6, 6), dtype=bool)
    for index in range(3):
        original[index, index * 2 : index * 2 + 2] = True
    actual = original.copy()
    actual[1] = False
    comparison = compare_masks(actual, original)
    assert comparison["actual_present_indexed_ids"] == [1, 3]
    assert comparison["objects"][1]["indexed_mask_agreement_iou"] == 0
    assert comparison["objects"][2]["indexed_mask_agreement_iou"] == 1


def test_original_slot_priority_is_explicit_when_binary_masks_overlap():
    original = np.zeros((2, 4, 4), dtype=bool)
    original[0, :2] = True
    original[1, 2:] = True
    actual = original.copy()
    actual[1, 0, 0] = True
    comparison = compare_masks(actual, original)
    assert comparison["actual_overlap_pixels"] == 1
    assert comparison["objects"][1]["binary_mask_agreement_iou"] == 8 / 9
    assert comparison["objects"][1]["indexed_mask_agreement_iou"] == 1
    assert actual[1, 0, 0]  # Reporting does not mutate the retained binary masks.
