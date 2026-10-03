"""Fixed, label-free anonymous-birth proposal functions for the entry control.

This module makes no model calls and never assigns a biological name. Existing
tracking, quarantine and scoring helpers remain unchanged.
"""

import numpy as np
from detection_box_consensus import correspondences


def intersection_over_smaller(left, right):
    width = max(0, min(left["x2"], right["x2"]) - max(left["x1"], right["x1"]))
    height = max(0, min(left["y2"], right["y2"]) - max(left["y1"], right["y1"]))
    area = min(
        (left["x2"] - left["x1"]) * (left["y2"] - left["y1"]),
        (right["x2"] - right["x1"]) * (right["y2"] - right["y1"]),
    )
    return width * height / area if area > 0 else 0.0


def birth_candidates(proposals, active_boxes, previous_pending, rules):
    """Require two uniquely associated, separate, nonduplicate raw proposals.

    The caller replaces pending at every exact half second. A disappearing or
    ambiguous proposal therefore cannot accrue confirmation across a gap.
    Mature proposals are consumed even if later SAM validation rejects them.
    """
    _, represented = correspondences(active_boxes, proposals, rules["pair_iou"])
    occupied = [*active_boxes, *(proposals[j] for j in represented.values())]
    candidates = [
        index
        for index, box in enumerate(proposals)
        if index not in represented.values()
        and all(
            intersection_over_smaller(box, old) <= rules["maximum_occupied_overlap"]
            for old in occupied
        )
    ]
    duplicate = {
        i
        for i in candidates
        for j in candidates
        if i != j
        and intersection_over_smaller(proposals[i], proposals[j])
        >= rules["duplicate_overlap"]
    }
    candidates = [i for i in candidates if i not in duplicate]
    edges = [
        (i, j)
        for i in candidates
        for j, old in enumerate(previous_pending)
        if intersection_over_smaller(proposals[i], old) >= rules["temporal_overlap"]
    ]
    mature = [
        i
        for i, j in edges
        if sum(a == i for a, _ in edges) == 1 and sum(b == j for _, b in edges) == 1
    ]
    ambiguous = {
        i
        for i, j in edges
        if sum(a == i for a, _ in edges) != 1 or sum(b == j for _, b in edges) != 1
    }
    pending = [
        proposals[i] for i in candidates if i not in mature and i not in ambiguous
    ]
    return mature, pending


def valid_birth_masks(masks, boxes, previous_mask, rules):
    """Abstain on wrong-prompt support or foreground shared with another slot."""
    if len(masks) != len(boxes) or masks.shape[1:] != previous_mask.shape:
        raise ValueError("Birth masks must match the current source geometry")
    accepted = []
    active = [previous_mask == value for value in np.unique(previous_mask) if value]
    for index, (mask, box) in enumerate(zip(masks, boxes, strict=True)):
        area = int(mask.sum())
        inside = int(mask[box["y1"] : box["y2"], box["x1"] : box["x2"]].sum())
        if not area or inside / area < rules["minimum_prompt_support"]:
            continue
        if any(np.any(mask & other) for j, other in enumerate(masks) if j != index):
            continue
        if all(
            np.count_nonzero(mask & old) / min(area, np.count_nonzero(old))
            <= rules["maximum_mask_overlap"]
            for old in active
        ):
            accepted.append(index)
    return accepted


def register_anonymous_objects(tracker, object_ids):
    """Represent pre-birth absence without resetting established quarantine."""
    if len(set(object_ids)) != len(object_ids) or any(
        value <= 0 or value in tracker.object_ids for value in object_ids
    ):
        raise ValueError("Births require new, positive stable object IDs")
    tracker.object_ids = (*tracker.object_ids, *object_ids)
    for frame in tracker.history:
        for value in object_ids:
            frame.areas[value] = 0
            frame.probabilities[value] = 0.0


def indexed_birth_masks(masks, object_ids):
    """Only new foreground is prompted; zeros leave old memory to propagate."""
    if len(masks) != len(object_ids) or len(set(object_ids)) != len(object_ids):
        raise ValueError("Every mask requires its own new stable object ID")
    result = np.zeros(masks.shape[1:], dtype=np.int64)
    for mask, object_id in zip(masks, object_ids, strict=True):
        if object_id <= 0 or np.any(mask & (result != 0)):
            raise ValueError("Indexed birth masks cannot overlap or use background ID")
        result[mask] = object_id
    return result
