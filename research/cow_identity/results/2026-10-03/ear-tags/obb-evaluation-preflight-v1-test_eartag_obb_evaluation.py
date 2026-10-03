"""Exact crop joins and literal agreement must not hide extras or repair numbers."""

import pytest
from eartag_obb_evaluation import (
    read_conditions,
    validate_crop_rows,
    validate_reader_crops,
)


def test_geometry_join_rejects_missing_or_altered_prediction():
    detection = {"rows": [{"id": "tag", "predictions": [{"polygon": [1, 2, 3]}]}]}
    valid = [{"id": "tag", "index": 0, "polygon": [1, 2, 3]}]
    validate_crop_rows(valid, detection)
    for bad in ([], [{"id": "tag", "index": 0, "polygon": [1, 2, 4]}]):
        with pytest.raises(ValueError, match="same indexed geometry"):
            validate_crop_rows(bad, detection)


def test_leading_zero_disagreement_rejects_but_retains_raw_predictions():
    first = [{"id": "tag", "index": 0, "polygon": [], "text": "0024", "score": 0.99}]
    output = read_conditions(first, {("tag", 0): {"text": "024"}})
    assert len(output["rapid_raw"]) == len(output["trocr_raw"]) == 1
    assert output["literal_agreement"] == []
    first[0]["score"] = None
    assert read_conditions(first, {})["rapid_0.95"] == []


def test_readers_cannot_agree_on_different_crop_bytes():
    base = {"id": "tag", "index": 0, "polygon": [], "issue": None}
    prepared = [{**base, "sha256": "same"}]
    reading = [{**base, "crop_sha256": "same"}]
    validate_reader_crops(prepared, reading, reading)
    with pytest.raises(ValueError, match="identical prepared crop"):
        validate_reader_crops(prepared, reading, [{**base, "crop_sha256": "different"}])
