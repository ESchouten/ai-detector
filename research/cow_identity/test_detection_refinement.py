"""Refinement changes geometry only; original identity gates still decide names."""

import numpy as np
from detection_refinement import measure


def box(track, bounds):
    return dict(zip(("x1", "y1", "x2", "y2"), bounds, strict=True)) | {
        "track_id": track,
        "label": "cow",
        "confidence": 1.0,
    }


def test_sparse_refinement_keeps_rejected_and_anonymous_names_disabled():
    original = [
        box(0, [5, 25, 25, 75]),
        box(1, [40, 25, 60, 75]),
        box(2, [75, 25, 95, 75]),
    ]
    refined = [box(0, [75, 25, 95, 75]), box(1, [40, 25, 60, 75])]
    frames = [
        {
            "second": second,
            "boxes": original,
            "objects": [
                {"track_id": 0, "p10_probability": 0.9},
                {"track_id": 1, "p10_probability": 0.1},
                {"track_id": 2, "p10_probability": 0.9},
            ],
        }
        for second in range(2)
    ]
    value = {
        "timeline": frames,
        "provenance": {"seed_prompts": [{"cow": cow} for cow in (1, 2, 7)]},
    }
    cached = {
        "rows": [
            {"second": second, "original": original, "refined": refined}
            for second in range(2)
        ]
    }
    records = {
        "frame_id": np.repeat([1, 21], 3),
        "cow_id": np.tile([1, 2, 7], 2),
        "x_center": np.tile([0.15, 0.5, 0.85], 2),
        "y_center": np.full(6, 0.5),
        "width": np.full(6, 0.2),
        "height": np.full(6, 0.5),
    }
    result = measure(
        value,
        cached,
        {"source_fps": 20, "width": 100, "height": 100},
        {"last_processed_second": 1, "named_cows": [1, 2]},
        {"seconds": [0, 1], "minimum_p10_probability": 0.7},
        {"conflicted_ids_by_second": {"0": [], "1": []}},
        records,
    )
    assert result["original"]["counts"]["correct_name"] == 2
    assert result["original"]["counts"]["known_unnamed"] == 2
    assert result["original"]["counts"]["unknown_rejected"] == 2
    assert result["refined"]["counts"]["correct_name"] == 0
    assert result["refined"]["counts"]["unknown_named"] == 2
    assert result["refined"]["counts"]["known_unnamed"] == 2
    assert result["refined"]["counts"]["visible_known"] == 4
    assert result["refined"]["counts"]["missed_annotations"] == 2
