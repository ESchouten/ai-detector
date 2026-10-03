"""Keep all proposals and the exact recorded name-to-proposal relationship."""

import pytest
from detection_output_geometry import baseline_boxes, detector_boxes
from video_assessment import VideoMetrics


def sample_frame():
    return {
        "boxes": [dict(x1=25, y1=25, x2=75, y2=75, track_id=0)],
        "named_track_ids": [0],
        "reciprocal_pairs": [{"track_id": 0, "proposal_index": 1}],
        "raw_detector_boxes": [
            dict(x1=0, y1=0, x2=10, y2=10, confidence=0.41),
            dict(x1=20, y1=20, x2=80, y2=80, confidence=0.92),
        ],
    }


def test_raw_geometry_retains_unnamed_false_proposals_and_recorded_pair():
    frame = sample_frame()
    boxes = detector_boxes(frame, [{"cow": 1}])
    assert len(boxes) == 2
    assert boxes[0].identity is None
    assert boxes[0].track_id is None
    assert boxes[0].confidence == 0.41
    assert boxes[1].track_id == 0
    assert boxes[1].identity.identity_id == f"{1:032x}"
    assert (boxes[1].x1, boxes[1].y1, boxes[1].x2, boxes[1].y2) == (20, 20, 80, 80)
    assert baseline_boxes(frame, [{"cow": 1}])[0].x1 == 25


def test_unconfirmed_reciprocal_partner_stays_unnamed():
    frame = sample_frame()
    frame["named_track_ids"] = []
    assert all(
        box.identity is None and box.track_id is None
        for box in detector_boxes(frame, [{"cow": 1}])
    )


def test_missing_or_shared_partner_cannot_silently_drop_a_name():
    frame = sample_frame()
    frame["named_track_ids"] = [0, 1]
    with pytest.raises(ValueError, match="Every emitted name"):
        detector_boxes(frame, [{"cow": 1}, {"cow": 2}])
    frame["reciprocal_pairs"].append({"track_id": 1, "proposal_index": 1})
    with pytest.raises(ValueError, match="ambiguous"):
        detector_boxes(frame, [{"cow": 1}, {"cow": 2}])


def test_added_unnamed_duplicate_can_steal_truth_assignment_and_counts_as_error():
    frame = sample_frame()
    frame["raw_detector_boxes"][0] = dict(x1=20, y1=20, x2=80, y2=80)
    frame["raw_detector_boxes"][1] = dict(x1=22, y1=22, x2=78, y2=78)
    boxes = detector_boxes(frame, [{"cow": 1}])
    metric = VideoMetrics()
    metric.add(0, boxes, [{"cow": 1, "box": [20, 20, 80, 80]}], [True, True])
    assert metric.counts["correct_name"] == 0
    assert metric.counts["known_unnamed"] == 1
    assert metric.counts["unmatched_named"] == 1
    assert metric.counts["detector_boxes"] == 2
