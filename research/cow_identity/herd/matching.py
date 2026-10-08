"""One-to-one association of predicted boxes with annotated boxes."""

import lap
import numpy as np


def overlap(first, second):
    """Intersection over union for every pair of (x1, y1, x2, y2) boxes."""
    first = np.asarray(first, dtype=np.float64).reshape(-1, 4)
    second = np.asarray(second, dtype=np.float64).reshape(-1, 4)
    left = np.maximum(first[:, None, 0], second[None, :, 0])
    top = np.maximum(first[:, None, 1], second[None, :, 1])
    right = np.minimum(first[:, None, 2], second[None, :, 2])
    bottom = np.minimum(first[:, None, 3], second[None, :, 3])
    shared = np.clip(right - left, 0, None) * np.clip(bottom - top, 0, None)
    area_first = (first[:, 2] - first[:, 0]) * (first[:, 3] - first[:, 1])
    area_second = (second[:, 2] - second[:, 0]) * (second[:, 3] - second[:, 1])
    union = area_first[:, None] + area_second[None, :] - shared
    return np.divide(shared, union, out=np.zeros_like(shared), where=union > 0)


def match(truth, predicted, threshold=0.5):
    """Pairs (truth index, predicted index): as many as possible, then best overlap."""
    if len(truth) == 0 or len(predicted) == 0:
        return []
    scores = overlap(truth, predicted)
    # A valid pair always outweighs any gain in overlap, so the count comes first.
    gain = np.where(scores >= threshold, 2.0 + scores, 0.0)
    _, assigned, _ = lap.lapjv(-gain, extend_cost=True)
    return [
        (row, int(column))
        for row, column in enumerate(assigned)
        if column >= 0 and scores[row, column] >= threshold
    ]
