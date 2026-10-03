"""Anonymous foreground selection and geometry for continuous camera tracking.

These pixel operations preserve the frozen startup containment policy. They
neither assign identities nor turn segmentation quality into class confidence.
The owning camera worker allocates stable IDs after selection.
"""

from dataclasses import dataclass
from typing import Literal, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from aidetector.domain.models import BoundingBox

MaskRejection = Literal[
    "empty_mask",
    "prompt_support",
    "duplicate_mask",
    "multi_part_parent_ambiguity",
    "contained_fragment",
    "ambiguous_overlap",
]


@dataclass(frozen=True)
class SeedSelection:
    """Disjoint masks in confidence order, with their original proposal indices."""

    proposal_indices: tuple[int, ...]
    masks: NDArray[np.bool_]
    rejections: tuple[tuple[MaskRejection, ...], ...]


def select_startup_masks(
    masks: NDArray[np.bool_], proposals: tuple[BoundingBox, ...]
) -> SeedSelection:
    """Keep one supported animal per mask; reject unresolved overlaps on both sides.

    A larger mask can suppress a contained fragment, but cannot suppress two
    separate animals it contains. Original masks and proposal order are never
    mutated. Small/border animals remain eligible; naming quality is separate.
    """
    if masks.ndim != 3 or masks.dtype != bool or len(masks) != len(proposals):
        raise ValueError("Startup needs one source-sized boolean mask per proposal")
    if any(box.confidence is None for box in proposals):
        raise ValueError("Startup proposals require actual detection confidence")
    confidences = tuple(cast(float, box.confidence) for box in proposals)
    order = sorted(range(len(proposals)), key=lambda i: (-confidences[i], i))
    areas = np.count_nonzero(masks, axis=(1, 2))
    kept, reasons = _supported_unique(masks, proposals, areas, order)
    _reject_contained_fragments(masks, areas, kept, confidences, reasons)

    # Ambiguous parents still participate: removing them must not make a
    # colliding neighbor look safe. Only proven contained fragments disappear.
    residual = [i for i in kept if "contained_fragment" not in reasons[i]]
    ambiguous = {
        endpoint
        for index, left in enumerate(residual)
        for right in residual[index + 1 :]
        if _overlap_of_smaller(masks, areas, left, right) > 0.1
        for endpoint in (left, right)
    }
    for i in ambiguous:
        reasons[i].append("ambiguous_overlap")
    selected = tuple(i for i in kept if not reasons[i])
    disjoint = np.zeros((len(selected), *masks.shape[1:]), dtype=bool)
    occupied = np.zeros(masks.shape[1:], dtype=bool)
    for position, i in enumerate(selected):
        disjoint[position] = masks[i] & ~occupied
        occupied |= disjoint[position]
    disjoint.setflags(write=False)
    return SeedSelection(selected, disjoint, tuple(tuple(row) for row in reasons))


def _supported_unique(
    masks: NDArray[np.bool_],
    proposals: tuple[BoundingBox, ...],
    areas: NDArray[np.intp],
    order: list[int],
) -> tuple[list[int], list[list[MaskRejection]]]:
    reasons: list[list[MaskRejection]] = [[] for _ in proposals]
    kept = []
    for i in order:
        box = proposals[i]
        if not areas[i]:
            reasons[i].append("empty_mask")
        elif (
            np.count_nonzero(masks[i, box.y1 : box.y2, box.x1 : box.x2]) / areas[i]
            < 0.9
        ):
            reasons[i].append("prompt_support")
        elif any(_mask_iou(masks[i], masks[j]) >= 0.8 for j in kept):
            reasons[i].append("duplicate_mask")
        else:
            kept.append(i)

    return kept, reasons


def _reject_contained_fragments(
    masks: NDArray[np.bool_],
    areas: NDArray[np.intp],
    kept: list[int],
    confidences: tuple[float, ...],
    reasons: list[list[MaskRejection]],
) -> None:
    contains = {
        parent: [
            child
            for child in kept
            if areas[parent] > areas[child]
            and np.count_nonzero(masks[parent] & masks[child]) / areas[child] >= 0.9
        ]
        for parent in kept
    }
    for parent, children in contains.items():
        if any(
            _overlap_of_smaller(masks, areas, left, right) <= 0.1
            for index, left in enumerate(children)
            for right in children[index + 1 :]
        ):
            for i in (parent, *children):
                if "multi_part_parent_ambiguity" not in reasons[i]:
                    reasons[i].append("multi_part_parent_ambiguity")

    for parent in sorted(kept, key=lambda i: (-areas[i], -confidences[i], i)):
        if not reasons[parent]:
            for child in contains[parent]:
                if not reasons[child]:
                    reasons[child].append("contained_fragment")


def _mask_iou(left: NDArray[np.bool_], right: NDArray[np.bool_]) -> float:
    return float(np.count_nonzero(left & right) / np.count_nonzero(left | right))


def _overlap_of_smaller(
    masks: NDArray[np.bool_], areas: NDArray[np.intp], left: int, right: int
) -> float:
    return float(
        np.count_nonzero(masks[left] & masks[right]) / min(areas[left], areas[right])
    )


def foreground_boxes(mask: NDArray[np.int64], label: str) -> tuple[BoundingBox, ...]:
    """Bound the largest 8-connected component of each stable nonzero object ID.

    Retain the study's inclusive maximum pixel coordinates and deterministic
    WU component ordering. A one-pixel-wide fragment is not a display box.
    Class confidence remains absent until an actual detector corroborates it.
    """
    boxes = []
    for object_id in np.unique(mask):
        if not object_id:
            continue
        _, _, stats, _ = cv2.connectedComponentsWithStatsWithAlgorithm(
            (mask == object_id).astype(np.uint8), 8, cv2.CV_32S, cv2.CCL_WU
        )
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, width, height, _ = map(int, stats[component])
        if width > 1 and height > 1:
            boxes.append(
                BoundingBox(
                    x, y, x + width - 1, y + height - 1, label, track_id=int(object_id)
                )
            )
    return tuple(boxes)
