import json
from types import SimpleNamespace

import numpy as np
import pytest
from passage_metrics import (
    full_frame_boxes,
    rates,
    score_frame,
    validate_prediction_timelines,
)
from passage_query import diverse_references, verify_freeze


def prediction(name=2234):
    return {
        "width": 1280,
        "height": 720,
        "boxes": [
            {
                "x1": 10,
                "y1": 20,
                "x2": 100,
                "y2": 200,
                "track_id": 1,
                "identity": {"identity_id": f"{name:032x}"},
            }
        ],
    }


def test_full_frame_scaling_and_unenrolled_known_denominator():
    frame = prediction()
    box = full_frame_boxes(frame, 1920, 1080)[0]
    assert (box.x1, box.y1, box.x2, box.y2) == (15, 30, 150, 300)
    truth = {
        "boxes": [
            {"cow": 2234, "box": [15, 30, 150, 300], "uncertain": False},
            {"cow": 2238, "box": [300, 300, 500, 500], "uncertain": False},
        ]
    }
    counts, _ = score_frame(frame, truth, {2234, 2238})
    assert counts["visible_known"] == 2 and counts["missed"] == 1
    assert rates(counts)["known_coverage"] == 0.5


def test_unknown_and_duplicate_predictions_stay_errors():
    frame = prediction()
    frame["boxes"].append(dict(frame["boxes"][0]))
    truth = {"boxes": [{"cow": None, "box": [15, 30, 150, 300], "uncertain": True}]}
    counts, _ = score_frame(frame, truth, {2234})
    assert counts["unknown_named"] == 1 and counts["unmatched_named"] == 1
    assert rates(counts)["conservative_named_precision"] == 0
    definite, _ = score_frame(frame, truth, {2234}, include_uncertain=False)
    assert definite["unknown_named"] == 0 and definite["unmatched_named"] == 1
    assert definite["visible_unknown"] == 0


def test_missing_intermediate_frames_are_not_silently_scored():
    clips = {"clip-a": {"frames": 31, "fps_numerator": 30, "fps_denominator": 1}}
    predictions = {
        "clips": [
            {"clip": "clip-a", "timeline": [{"local_frame": 0}, {"local_frame": 30}]}
        ]
    }
    with pytest.raises(ValueError, match="omit, duplicate or reorder"):
        validate_prediction_timelines(
            predictions, clips, {"processing_fps": 5, "sampling_fps": 1}
        )


def test_reference_selection_is_bounded_and_deterministic():
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    assert diverse_references([0, 1, 2], vectors, 2) == [0, 2]
    assert diverse_references([], vectors, 10) == []


def test_query_requires_explicit_frozen_annotation_approval(tmp_path):
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps({"status": "Annotations still in progress"}))
    with pytest.raises(ValueError, match="not been approved"):
        verify_freeze(SimpleNamespace(freeze=path))
