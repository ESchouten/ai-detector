from autocattlogger_pose_pilot import selected_indices


def test_selection_spans_spatial_order_without_confidence_ranking():
    boxes = [
        {"x1": x, "x2": x + 2, "y1": 0, "y2": 3, "confidence": confidence}
        for x, confidence in [(8, 0.99), (2, 0.2), (6, 0.7), (0, 0.1), (4, 0.3)]
    ]
    assert selected_indices(boxes) == [3, 1, 4, 0]
    for box in boxes:
        box["confidence"] = 1 - box["confidence"]
    assert selected_indices(boxes) == [3, 1, 4, 0]


def test_missing_detections_are_not_duplicated_or_replaced():
    assert selected_indices([]) == []
    assert selected_indices(
        [
            {"x1": 10, "x2": 20, "y1": 1, "y2": 3},
            {"x1": 0, "x2": 5, "y1": 1, "y2": 3},
        ]
    ) == [1, 0]
