import pytest
from recognition_masked_gallery import consensus


def review(rows):
    return {
        "rows": [
            {"candidate": i, "accepted": accepted, "cow": cow}
            for i, accepted, cow in rows
        ]
    }


def test_uncertainty_or_disagreement_rejects_without_majority_override():
    a = review([(0, True, 2), (1, True, 1), (2, True, 3)])
    b = review([(0, True, 2), (1, False, None), (2, True, 4)])
    rows = consensus({"a": a, "b": b, "c": a}, range(3))
    assert [(r["accepted"], r["cow"]) for r in rows] == [
        (True, 2),
        (False, None),
        (False, None),
    ]
    assert rows[2]["reviews"]["b"]["cow"] == 4


def test_missing_or_duplicate_question_cannot_silently_change_gallery():
    valid = review([(0, True, 2), (1, False, None)])
    with pytest.raises(ValueError, match="every question"):
        consensus({"a": valid, "b": review([(0, True, 2)])}, range(2))
    with pytest.raises(ValueError, match="Duplicate"):
        consensus({"a": valid, "b": review([(0, True, 2), (0, True, 2)])}, range(2))


def test_confirmed_biological_id_is_not_inferred_from_question_number():
    value = review([(12, True, 6)])
    assert consensus({"a": value, "b": value}, [12])[0]["cow"] == 6
