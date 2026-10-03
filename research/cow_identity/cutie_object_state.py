"""Stable object IDs must not be confused with compacted Cutie tensor channels."""

import numpy as np
from detection_cutie import boxes_from_mask


def stable_mask_diagnostics(mask, probabilities, object_to_channel):
    """Summarize current channels using an explicit upstream ObjectManager mapping.

    A future dynamic runner obtains the mapping with find_tmp_by_id(object_id)
    after each addition/deletion. This does not modify the fixed-slot runner.
    """
    objects = []
    if probabilities.shape[1:] != mask.shape:
        raise ValueError("Probability maps and indexed masks have different geometry")
    if len(set(object_to_channel.values())) != len(object_to_channel):
        raise ValueError("Two stable objects cannot share one probability channel")
    for box in boxes_from_mask(mask):
        object_id = box["track_id"] + 1
        channel = object_to_channel.get(object_id)
        if channel is None or not 0 < channel < probabilities.shape[0]:
            raise ValueError("Visible stable object has no current probability channel")
        pixels = mask == object_id
        confidence = probabilities[channel][pixels]
        if not np.isfinite(confidence).all():
            raise ValueError("Object probabilities must be finite")
        objects.append(
            {
                "track_id": object_id - 1,
                "area": int(pixels.sum()),
                "mean_probability": float(confidence.mean()),
                "p10_probability": float(np.quantile(confidence, 0.1)),
            }
        )
    return objects
