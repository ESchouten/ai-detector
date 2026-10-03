import copy

import pytest
from eartag_localization_evaluate import counts, size_bin, validate_raw


def test_duplicate_predictions_and_missed_tags_remain_in_denominators():
    result = counts(
        [
            {"xyxy": [0, 0, 10, 10]},
            {"xyxy": [0, 0, 10, 10]},
            {"xyxy": [50, 50, 60, 60]},
        ],
        [{"xyxy": [0, 0, 10, 10]}, {"xyxy": [20, 20, 30, 30]}],
    )
    assert result["matched"] == 1
    assert result["missed"] == 1
    assert result["unmatched_predictions"] == 2
    assert counts([], [{"xyxy": [0, 0, 10, 10]}])["missed"] == 1
    assert counts([{"xyxy": [0, 0, 10, 10]}], [])["unmatched_predictions"] == 1


def test_complete_source_binding_precedes_any_scoring():
    row = {
        "id": "image",
        "shape": [100, 100, 3],
        "pixels_sha256": "pixels",
        "panel": "development",
    }
    document = {"rows": [row]}
    raw = {
        "status": "COMPLETE_RAW_BEFORE_SCORE",
        "protocol_sha256": "protocol",
        "rows": [
            {**row, "boxes": [{"class": 1, "confidence": 0.25, "xyxy": [0, 0, 10, 10]}]}
        ],
    }
    validate_raw(document, raw, "protocol")
    for key, value in (
        ("pixels_sha256", "different"),
        ("id", "other"),
        ("panel", "evaluation"),
    ):
        invalid = copy.deepcopy(raw)
        invalid["rows"][0][key] = value
        with pytest.raises(ValueError):
            validate_raw(document, invalid, "protocol")
    for box in (
        {"class": 2, "confidence": 0.9, "xyxy": [0, 0, 10, 10]},
        {"class": 1, "confidence": float("nan"), "xyxy": [0, 0, 10, 10]},
        {"class": 1, "confidence": 0.9, "xyxy": [-1, 0, 10, 10]},
    ):
        invalid = copy.deepcopy(raw)
        invalid["rows"][0]["boxes"] = [box]
        with pytest.raises(ValueError):
            validate_raw(document, invalid, "protocol")


def test_size_boundaries_are_predeclared_not_outcome_selected():
    assert [size_bin(v) for v in (15.99, 16, 31.99, 32, 63.99, 64)] == [
        "<16",
        "16–32",
        "16–32",
        "32–64",
        "32–64",
        ">=64",
    ]
