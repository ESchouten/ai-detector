"""Union changes geometry only, including unnamed slots without adding proposals."""

from detection_union_geometry import union_boxes


def test_union_does_not_shrink_mask_or_change_identity_and_discards_no_slot():
    frame = {
        "boxes": [
            dict(x1=10, y1=20, x2=60, y2=70, track_id=0, confidence=0.8),
            dict(x1=80, y1=20, x2=90, y2=30, track_id=1),
        ],
        "named_track_ids": [0],
        "reciprocal_pairs": [{"track_id": 0, "proposal_index": 0}],
        "raw_detector_boxes": [
            dict(x1=15, y1=5, x2=50, y2=80),
            dict(x1=0, y1=0, x2=100, y2=100),
        ],
    }
    boxes = union_boxes(frame, [{"cow": 1}, {"cow": 2}])
    assert len(boxes) == 2
    assert (boxes[0].x1, boxes[0].y1, boxes[0].x2, boxes[0].y2) == (10, 5, 60, 80)
    assert boxes[0].identity.identity_id == f"{1:032x}"
    assert boxes[0].confidence == 0.8
    assert boxes[1].identity is None
    assert boxes[1].track_id == 1
    assert (boxes[1].x1, boxes[1].y1, boxes[1].x2, boxes[1].y2) == (80, 20, 90, 30)


def test_unnamed_reciprocal_slot_uses_same_geometry_rule_without_acquiring_name():
    frame = {
        "boxes": [dict(x1=10, y1=10, x2=40, y2=40, track_id=0)],
        "named_track_ids": [],
        "reciprocal_pairs": [{"track_id": 0, "proposal_index": 0}],
        "raw_detector_boxes": [dict(x1=5, y1=5, x2=50, y2=50)],
    }
    box = union_boxes(frame, [{"cow": 1}])[0]
    assert box.identity is None
    assert box.track_id == 0
    assert (box.x1, box.y1, box.x2, box.y2) == (5, 5, 50, 50)
