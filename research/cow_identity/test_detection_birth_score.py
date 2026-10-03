"""New opaque slots must not become publisher cow IDs in the shared scorer."""

import numpy as np
from detection_sam_tracking import score


def test_new_slot_seven_stays_anonymous_when_truth_is_cow_seven():
    records = {
        "frame_id": np.array([1, 1]),
        "cow_id": np.array([1, 7]),
        "x_center": np.array([0.25, 0.75]),
        "y_center": np.array([0.5, 0.5]),
        "width": np.array([0.4, 0.4]),
        "height": np.array([0.8, 0.8]),
    }
    value = {
        "timeline": [
            {
                "second": 0,
                "named_track_ids": [0],
                "boxes": [
                    {
                        "x1": 5,
                        "y1": 10,
                        "x2": 45,
                        "y2": 90,
                        "track_id": 0,
                        "label": "cow",
                    },
                    {
                        "x1": 55,
                        "y1": 10,
                        "x2": 95,
                        "y2": 90,
                        "track_id": 6,
                        "label": "cow",
                    },
                ],
            }
        ]
    }
    slots = [*({"cow": i} for i in range(1, 7)), {"cow": None}, {"cow": None}]
    result = score(
        value,
        records,
        {"source_fps": 20, "width": 100, "height": 100},
        {
            "last_processed_second": 0,
            "score_seconds": [0, 0],
            "named_cows": list(range(1, 7)),
        },
        slots,
        name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
    )
    counts = result["naming_counts"]
    assert counts["visible_known"] == counts["visible_unknown"] == 1
    assert counts["correct_name"] == counts["unknown_rejected"] == 1
    assert counts["unknown_named"] == 0
