import numpy as np
import pytest

from aidetector.adapters.inference.identity_masks import (
    foreground_boxes,
    select_startup_masks,
)
from aidetector.domain.models import BoundingBox


def proposals(count, width=20, height=20):
    return tuple(
        BoundingBox(0, 0, width, height, "cow", 0.9 - i * 0.01) for i in range(count)
    )


def test_duplicate_and_contained_fragment_leave_one_complete_animal():
    masks = np.zeros((4, 20, 20), dtype=bool)
    masks[0, 2:18, 2:18] = True
    masks[1] = masks[0]
    masks[2, 4:12, 4:12] = True
    original = masks.copy()
    result = select_startup_masks(masks, proposals(4))
    assert result.proposal_indices == (0,)
    assert result.rejections == (
        (),
        ("duplicate_mask",),
        ("contained_fragment",),
        ("empty_mask",),
    )
    assert np.array_equal(result.masks[0], original[0])
    assert np.array_equal(masks, original)
    assert not result.masks.flags.writeable


def test_merged_parent_cannot_suppress_two_distinct_animals():
    masks = np.zeros((3, 20, 20), dtype=bool)
    masks[0, 2:18, 2:18] = True
    masks[1, 2:18, 2:9] = True
    masks[2, 2:18, 11:18] = True
    result = select_startup_masks(masks, proposals(3))
    assert result.proposal_indices == ()
    assert result.masks.shape == (0, 20, 20)
    assert all("multi_part_parent_ambiguity" in row for row in result.rejections)


def test_uncertain_overlap_rejects_both_animals_but_small_overlap_is_disjoint():
    masks = np.zeros((2, 20, 20), dtype=bool)
    masks[0, 2:18, 1:11] = True
    masks[1, 2:18, 9:19] = True
    rejected = select_startup_masks(masks, proposals(2))
    assert rejected.rejections == (("ambiguous_overlap",), ("ambiguous_overlap",))
    masks[1] = False
    masks[1, 2:18, 10:20] = True
    accepted = select_startup_masks(masks, proposals(2))
    assert accepted.proposal_indices == (0, 1)
    assert not np.any(accepted.masks[0] & accepted.masks[1])
    assert np.array_equal(accepted.masks[0] | accepted.masks[1], masks[0] | masks[1])


def test_unsupported_mask_rejected_without_hiding_valid_border_animal():
    masks = np.zeros((2, 20, 20), dtype=bool)
    masks[0, 8:18, 8:18] = True
    masks[1, :4, :4] = True
    result = select_startup_masks(
        masks, (BoundingBox(0, 0, 10, 10, "cow", 0.9), proposals(1)[0])
    )
    assert result.proposal_indices == (1,)
    assert result.rejections == (("prompt_support",), ())
    with pytest.raises(ValueError, match="confidence"):
        select_startup_masks(masks[:1], (BoundingBox(0, 0, 20, 20),))


def test_component_geometry_preserves_stable_ids_without_invented_confidence():
    mask = np.zeros((20, 20), dtype=np.int64)
    mask[2:7, 3:9] = 42
    mask[15:17, 15:17] = 42  # Smaller disconnected fragment is excluded.
    mask[10:15, 2:7] = 7
    mask[1:10, 19] = 105  # No width, hence no display box.
    assert foreground_boxes(mask, "cow") == (
        BoundingBox(2, 10, 6, 14, "cow", track_id=7),
        BoundingBox(3, 2, 8, 6, "cow", track_id=42),
    )
