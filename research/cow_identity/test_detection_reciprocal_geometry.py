from copy import deepcopy

import pytest
from detection_reciprocal_geometry import substitute_frame


def example():
    return {
        "boxes": [
            dict(x1=0, y1=0, x2=10, y2=10, confidence=0.95, label="cow", track_id=2),
            dict(x1=20, y1=20, x2=40, y2=40, confidence=0.8, label="cow", track_id=7),
            dict(x1=50, y1=50, x2=60, y2=60, confidence=0.7, label="cow", track_id=9),
        ],
        "raw_detector_boxes": [
            dict(x1=1, y1=2, x2=15, y2=16, confidence=0.6),
            dict(x1=21, y1=22, x2=38, y2=39, confidence=0.5),
            dict(x1=100, y1=100, x2=130, y2=130, confidence=0.9),
        ],
        "reciprocal_pairs": [
            {"track_id": 2, "proposal_index": 0},
            {"track_id": 7, "proposal_index": 1},
        ],
        "named_track_ids": [2],
        "conflicted_ids": [8],
        "second": 330,
    }


def test_original_slots_order_names_and_unpaired_geometry_survive():
    frame = example()
    original = deepcopy(frame)
    result = substitute_frame(frame)
    assert frame == original
    assert [b["track_id"] for b in result["boxes"]] == [2, 7, 9]
    assert result["boxes"][0] == {
        **original["boxes"][0],
        **frame["raw_detector_boxes"][0],
    }
    assert result["boxes"][1] == {
        **original["boxes"][1],
        **frame["raw_detector_boxes"][1],
    }
    assert result["boxes"][2] == original["boxes"][2]
    assert {k: v for k, v in result.items() if k != "boxes"} == {
        k: v for k, v in original.items() if k != "boxes"
    }


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_proposal", "missing_named_partner", "unknown_slot", "bad_index"],
)
def test_ambiguous_or_missing_original_correspondence_rejected(mutation):
    frame = example()
    if mutation == "duplicate_proposal":
        frame["reciprocal_pairs"][1]["proposal_index"] = 0
    elif mutation == "missing_named_partner":
        frame["reciprocal_pairs"] = frame["reciprocal_pairs"][1:]
    elif mutation == "unknown_slot":
        frame["reciprocal_pairs"][1]["track_id"] = 11
    else:
        frame["reciprocal_pairs"][1]["proposal_index"] = 15
    with pytest.raises(ValueError, match="unique recorded"):
        substitute_frame(frame)
