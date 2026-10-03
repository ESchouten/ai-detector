"""CPU checks for exact timestamps, unknown/empty failures and policy reuse."""

from unittest.mock import Mock

import numpy as np
import pytest
from detection_streaming import decide_frame
from passage_entry_control import OneHertzQuarantine
from passage_entry_score import measure


def test_half_second_evidence_does_not_double_quarantine_history():
    tracker = Mock()
    tracker.observe_evidence.side_effect = [{1}, set()]
    clock = OneHertzQuarantine(tracker)
    mask = np.zeros((8, 8), dtype=np.uint8)
    assert clock.observe_evidence(0, mask, {}, [], []) == {1}
    assert clock.observe_evidence(0.5, mask, {}, [], []) == {1}
    assert clock.observe_evidence(1, mask, {}, [], []) == set()
    assert [call.args[0] for call in tracker.observe_evidence.call_args_list] == [0, 1]
    with pytest.raises(ValueError, match="half-second"):
        clock.observe_evidence(1, mask, {}, [], [])


def test_half_second_naming_uses_fresh_detector_not_previous_corroboration():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[2:16, 3:18] = 1
    objects = [{"track_id": 0, "p10_probability": 0.9}]
    tracker = Mock()
    tracker.observe_evidence.return_value = set()
    clock = OneHertzQuarantine(tracker)
    box = {"x1": 3, "y1": 2, "x2": 17, "y2": 15, "confidence": 0.8}
    settings = {"minimum_iou": 0.5, "minimum_p10": 0.7}
    assert decide_frame(0, mask, objects, [box], clock, {1}, settings)[
        "named_track_ids"
    ] == [0]
    assert (
        decide_frame(0.5, mask, objects, [], clock, {1}, settings)["named_track_ids"]
        == []
    )


def test_every_half_second_unknown_and_empty_name_count_as_failures():
    box = {"x1": 10, "y1": 10, "x2": 100, "y2": 100, "track_id": 0}
    timeline = [
        {
            "second": i / 2,
            "width": 1920,
            "height": 1080,
            "boxes": [box],
            "named_track_ids": [0],
        }
        for i in range(22)
    ]
    truth = [{"second": i / 2, "boxes": []} for i in range(22)]
    truth[0]["boxes"] = [{"cow": 5676, "box": [10, 10, 100, 100], "uncertain": False}]
    truth[1]["boxes"] = [{"cow": 5953, "box": [10, 10, 100, 100], "uncertain": False}]
    result = measure(timeline, truth, {i / 2: 100 for i in range(22)})
    assert result["overall"]["counts"]["correct_names"] == 1
    assert result["lifecycle"]["inherited_name_on_entrant"] == 1
    assert result["lifecycle"]["names_in_empty_frames"] == 20
    assert result["lifecycle"]["empty_frames_with_any_mask_pixels"] == 20
    with pytest.raises(ValueError, match="all half-second"):
        measure(timeline[::2], truth, {})
