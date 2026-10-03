import numpy as np
from detection_cutie import boxes_from_mask, indexed_seed, resource_stop


def test_missing_object_does_not_renumber_remaining_seed_names():
    masks = np.zeros((3, 8, 8), dtype=bool)
    masks[0, 0:3, 0:3] = True
    masks[2, 2:6, 2:6] = True
    indexed = indexed_seed(masks)
    assert indexed[2, 2] == 1  # Existing slot wins overlap deterministically.
    assert [box["track_id"] for box in boxes_from_mask(indexed)] == [0, 2]


def test_memory_and_sustained_time_caps_are_independent_of_accuracy():
    limits = dict(
        max_mps_driver_bytes=100,
        max_peak_rss_bytes=200,
        warmup_frames=2,
        timing_window_frames=3,
        max_mean_seconds_per_frame=1,
    )
    assert resource_stop(101, 1, [], limits).startswith("MPS")
    assert resource_stop(1, 201, [], limits).startswith("Process")
    assert resource_stop(1, 1, [2] * 4, limits) is None
    assert resource_stop(1, 1, [2] * 5, limits).startswith("Sustained")
