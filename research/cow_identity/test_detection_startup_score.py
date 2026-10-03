from dataclasses import asdict

import pytest
from detection_startup_score import (
    continuity_counts,
    initial_associations,
    validate_complete,
)

from aidetector.domain.models import BoundingBox


def test_duplicate_initial_slots_do_not_gain_later_anchors():
    boxes = [BoundingBox(0, 0, 10, 10, track_id=i) for i in range(2)]
    truth = [{"cow": 11, "box": [0, 0, 10, 10]}]
    anchors = initial_associations(boxes, truth)
    assert len(anchors) == 1
    frame = {"second": 1, "boxes": [asdict(b) for b in boxes], "truth": truth}
    counts = continuity_counts([frame], anchors)["counts"]
    assert counts["visible_annotations"] == 1
    assert counts["predictions"] == 2
    assert counts["unmatched_unanchored"] + counts["unmatched_anchored"] == 1


def test_swapped_instances_are_wrong_even_when_all_geometry_is_perfect():
    boxes = [
        BoundingBox(0, 0, 10, 10, track_id=0),
        BoundingBox(20, 0, 30, 10, track_id=1),
    ]
    truth = [{"cow": 11, "box": [0, 0, 10, 10]}, {"cow": 12, "box": [20, 0, 30, 10]}]
    anchors = initial_associations(boxes, truth)
    swapped = [{**asdict(b), "track_id": 1 - b.track_id} for b in boxes]
    counts = continuity_counts(
        [{"second": 1, "boxes": swapped, "truth": truth}], anchors
    )["counts"]
    assert counts["matched"] == 2
    assert counts["correct_initial_instance"] == 0
    assert counts["wrong_initial_instance"] == 2


def test_missed_truth_and_unanchored_track_remain_in_full_denominator():
    frame = {
        "second": 1,
        "boxes": [asdict(BoundingBox(0, 0, 10, 10, track_id=2))],
        "truth": [
            {"cow": 11, "box": [0, 0, 10, 10]},
            {"cow": 12, "box": [20, 0, 30, 10]},
        ],
    }
    result = continuity_counts([frame], {0: 11})
    assert result["counts"]["visible_annotations"] == 2
    assert result["counts"]["missed_annotations"] == 1
    assert result["counts"]["matched_unanchored"] == 1
    assert result["initial_instance_coverage"] == 0


def test_incomplete_run_cannot_be_scored_as_full_panel(tmp_path):
    with pytest.raises(ValueError, match="incomplete"):
        validate_complete({"complete": False, "stop_reason": "budget"}, {}, tmp_path)
