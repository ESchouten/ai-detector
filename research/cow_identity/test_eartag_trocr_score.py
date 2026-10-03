"""Real scoring pitfalls: literal zeros, lost crops and extra unmatched text."""

import pytest
from eartag_trocr_score import character_counts, edit_distance, validate_rows


def test_character_metric_preserves_zero_and_counts_miss_and_extra():
    assert edit_distance("0024", "024") == 1
    predictions = [{"text": "024"}, {"text": "extra"}]
    truth = [{"text": "0024"}, {"text": "8.1"}]
    result = {"matches": [{"truth_index": 0, "prediction": predictions[0]}]}
    assert character_counts(truth, predictions, result) == {
        "character_errors_including_misses_extras": 9,
        "truth_characters": 7,
    }


def test_complete_flag_cannot_hide_missing_crop():
    data = {
        "panels": {
            "oracle": [{"id": "a", "index": 0, "sha256": "x", "polygon": []}],
            "detected": [],
        }
    }
    with pytest.raises(ValueError, match="complete exact"):
        validate_rows({"complete": True, "error": None, "rows": []}, data)
