"""CPU checks for fixed anonymous births; no images or models are loaded."""

from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest
from passage_entry_birth_run import advance_once
from passage_entry_births import (
    birth_candidates,
    indexed_birth_masks,
    register_anonymous_objects,
    valid_birth_masks,
)

RULES = {
    "pair_iou": 0.5,
    "maximum_occupied_overlap": 0.1,
    "duplicate_overlap": 0.5,
    "temporal_overlap": 0.5,
    "minimum_prompt_support": 0.9,
    "maximum_mask_overlap": 0.1,
}


def box(x1, y1, x2, y2):
    return dict(zip(("x1", "y1", "x2", "y2"), (x1, y1, x2, y2), strict=True))


def test_nested_original_body_proposals_cannot_create_births():
    old = box(60, 0, 100, 100)
    duplicate = box(70, 10, 95, 70)
    new = box(0, 30, 25, 95)
    mature, pending = birth_candidates([old, duplicate, new], [old], [], RULES)
    assert mature == [] and pending == [new]
    mature, pending = birth_candidates([old, duplicate, new], [old], pending, RULES)
    assert mature == [2] and pending == []


def test_disappearance_restarts_confirmation_and_duplicate_candidates_abstain():
    new = box(0, 0, 20, 20)
    _, pending = birth_candidates([new], [], [], RULES)
    assert birth_candidates([], [], pending, RULES) == ([], [])
    assert birth_candidates([new], [], [], RULES) == ([], [new])
    assert birth_candidates([new, box(2, 2, 18, 18)], [], [new], RULES) == ([], [])


def test_competing_temporal_association_abstains_in_both_directions():
    left, right = box(0, 0, 20, 20), box(30, 0, 50, 20)
    spanning = box(0, 0, 50, 20)
    assert birth_candidates([spanning], [], [left, right], RULES) == ([], [])
    assert birth_candidates([left, right], [], [spanning], RULES) == ([], [])


def test_sam_overlap_and_wrong_prompt_support_reject_before_insertion():
    masks = np.zeros((2, 20, 40), bool)
    masks[0, 2:12, 2:12], masks[1, 2:12, 8:18] = True, True
    empty = np.zeros((20, 40), int)
    boxes = [box(0, 0, 20, 20)] * 2
    assert valid_birth_masks(masks, boxes, empty, RULES) == []
    assert valid_birth_masks(masks[:1], [box(20, 0, 40, 20)], empty, RULES) == []
    old = empty.copy()
    old[2:12, 2:12] = 42
    assert valid_birth_masks(masks[:1], boxes[:1], old, RULES) == []
    assert valid_birth_masks(masks[:1], boxes[:1], empty, RULES) == [0]


def test_noncontiguous_ids_do_not_reset_old_quarantine_history():
    frame = SimpleNamespace(areas={7: 12}, probabilities={7: 0.8}, mask=np.ones((2, 2)))
    conflict = object()
    tracker = SimpleNamespace(
        object_ids=(7,), history=deque([frame]), conflicts=conflict
    )
    register_anonymous_objects(tracker, [42])
    assert tracker.object_ids == (7, 42)
    assert tracker.history[0] is frame and tracker.conflicts is conflict
    assert frame.areas == {7: 12, 42: 0}
    assert frame.probabilities == {7: 0.8, 42: 0.0}
    np.testing.assert_array_equal(frame.mask, np.ones((2, 2)))
    masks = np.zeros((2, 4, 8), bool)
    masks[0, :, :2], masks[1, :, 6:] = True, True
    result = indexed_birth_masks(masks, [42, 91])
    assert set(np.unique(result)) == {0, 42, 91}
    with pytest.raises(ValueError, match="new, positive"):
        register_anonymous_objects(tracker, [42])
    with pytest.raises(ValueError, match="overlap"):
        indexed_birth_masks(np.stack([masks[0], masks[0]]), [42, 91])


def test_upstream_once_per_timestamp_with_only_new_indexed_ids():
    import torch
    from cutie.inference.object_manager import ObjectManager

    calls = []
    manager = ObjectManager()

    def step(tensor, mask=None, objects=None, idx_mask=False):
        calls.append((mask, objects, idx_mask))
        if objects is not None:
            manager.add_new_objects(objects)
        return tensor

    core = SimpleNamespace(step=step)
    tensor = torch.zeros((3, 4, 8))
    initial = torch.zeros((4, 8), dtype=torch.int64)
    initial[:, :2] = 1
    new = np.zeros((1, 4, 8), bool)
    new[0, :, 6:] = True
    for index in range(22):
        advance_once(
            core,
            tensor,
            initial if index == 0 else None,
            new,
            [42] if index == 3 else [],
        )
    assert len(calls) == 22
    assert calls[0][1:] == ([1], True)
    assert calls[3][1:] == ([42], True)
    assert set(calls[3][0].unique().tolist()) == {0, 42}
    assert all(mask is None for i, (mask, _, _) in enumerate(calls) if i not in (0, 3))
    assert manager.find_tmp_by_id(42) == 2
    manager.delete_objects([1])
    assert manager.find_tmp_by_id(42) == 1
    torch.testing.assert_close(initial[:, :2], torch.ones((4, 2), dtype=torch.int64))
