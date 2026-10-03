"""Guard seeded video identity and exact sampling rather than SDK model internals."""

from dataclasses import asdict
from unittest.mock import Mock

import detection_sam_tracking
import numpy as np
import pytest
import torch
from detection_sam_tracking import (
    RESOURCE_LIMITS,
    reclaim_mps_cache,
    resource_stop,
    sampled_seconds,
    score,
    visible_ids,
)

from aidetector.domain.models import BoundingBox


def test_missing_middle_mask_does_not_rename_later_objects():
    assert visible_ids([True, False, True], {0: 10, 1: 20, 2: 30}) == [10, 30]
    with pytest.raises(ValueError, match="slots"):
        visible_ids([True], {0: 10, 1: 20})


def test_resource_guard_allows_warmup_but_stops_sustained_load_and_memory_growth():
    memory = {"mps_driver_bytes": 1_000_000}
    assert resource_stop(memory, [8.0] * 10 + [0.25] * 30, RESOURCE_LIMITS) is None
    assert "frame-time" in resource_stop(
        memory, [0.1] * 10 + [1.2] * 30, RESOURCE_LIMITS
    )
    assert "memory" in resource_stop(
        {"mps_driver_bytes": 9 * 1024**3}, [0.1], RESOURCE_LIMITS
    )


def test_cache_reclamation_only_runs_above_budget_and_preserves_before_after(
    monkeypatch,
):
    before = {"mps_driver_bytes": 7 * 1024**3, "mps_allocated_bytes": 300_000_000}
    after = {"mps_driver_bytes": 3 * 1024**3, "mps_allocated_bytes": 300_000_000}
    memory = Mock(side_effect=[before, after, after])
    synchronize = Mock()
    empty = Mock()
    monkeypatch.setattr(detection_sam_tracking, "memory_usage", memory)
    monkeypatch.setattr(torch.mps, "synchronize", synchronize)
    monkeypatch.setattr(torch.mps, "empty_cache", empty)
    measured, reclamation = reclaim_mps_cache(object(), "mps", 6 * 1024**3)
    assert measured == after
    assert reclamation["before"] == before
    assert reclamation["after"] == after
    assert empty.call_count == 1
    assert synchronize.call_count == 2
    assert reclaim_mps_cache(object(), "mps", 6 * 1024**3) == (after, None)
    assert empty.call_count == 1


def test_sampling_seeds_actual_first_frame_and_never_reads_next_window():
    seconds = sampled_seconds({"processing_fps": 2, "last_processed_second": 629})
    assert seconds[:3] == [0.0, 0.5, 1.0]
    assert seconds[-1] == 629
    assert len(seconds) == 1259
    assert (
        len(
            [
                second
                for second in seconds
                if 330 <= second <= 629 and second.is_integer()
            ]
        )
        == 300
    )


def test_seeded_names_count_wrong_cow_unknown_and_unmatched_separately():
    records = {
        "frame_id": np.full(4, 6601),
        "cow_id": np.array([1, 7, 2, 3]),
        "x_center": np.array([0.05, 0.25, 0.45, 0.85]),
        "y_center": np.full(4, 0.05),
        "width": np.full(4, 0.1),
        "height": np.full(4, 0.1),
    }
    boxes = [
        asdict(BoundingBox(x, 0, x + 10, 10, track_id=track))
        for x, track in ((0, 0), (20, 1), (40, 2), (60, 3), (80, 6))
    ]
    inputs = (
        {
            "timeline": [
                {"second": second, "boxes": boxes if second == 330 else []}
                for second in range(331)
            ]
        },
        records,
        {"source_fps": 20, "width": 100, "height": 100},
        {
            "score_seconds": [330, 330],
            "last_processed_second": 330,
            "named_cows": [1, 2, 3, 4, 5, 6],
        },
    )
    seeds = [{"cow": cow} for cow in range(1, 9)]
    result = score(*inputs, seeds)
    counts = result["naming_counts"]
    assert [
        counts[name]
        for name in ("correct_name", "wrong_name", "unknown_named", "unmatched_named")
    ] == [1, 1, 1, 1]
    assert counts["known_unnamed"] == 1
    assert result["known_coverage"] == 1 / 3
    assert result["conservative_precision"] == 0.25
    swapped = [seeds[1], seeds[0], *seeds[2:]]
    incorrect_seed = score(*inputs, swapped)
    assert (
        incorrect_seed["tracking"]["global_identity_f1"]
        == result["tracking"]["global_identity_f1"]
    )
    assert incorrect_seed["conservative_precision"] == 0.0
    rejected = score(*inputs, seeds, name_allowed=lambda frame, box: box.track_id != 0)
    assert rejected["naming_counts"]["correct_name"] == 0
    assert rejected["naming_counts"]["known_unnamed"] == 2
    assert rejected["tracking"] == result["tracking"]


def test_incomplete_cached_propagation_cannot_shrink_the_scoring_denominator():
    with pytest.raises(ValueError, match="every frozen"):
        score(
            {"timeline": [{"second": 0}, {"second": 2}]},
            {},
            {},
            {"last_processed_second": 2},
            [],
        )
