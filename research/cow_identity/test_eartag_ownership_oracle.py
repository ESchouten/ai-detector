import pytest
from eartag_ownership_oracle import choices, contained, outcome, predict


def test_containment_is_directional_and_includes_exact_ninety_percent():
    assert contained([0, 0, 10, 10], [1, 0, 21, 10]) == 0.9
    assert contained([1, 0, 21, 10], [0, 0, 10, 10]) == 0.45
    assert (
        choices([0, 0, 10, 10], [{"id": "one", "xyxy": [1, 0, 21, 10]}])["selected"]
        == "one"
    )
    with pytest.raises(ValueError):
        contained([0, 0, float("nan"), 10], [0, 0, 10, 10])


def test_uncertain_competing_body_still_forces_abstention_and_truth_is_not_input():
    row = {
        "id": "synthetic",
        "bodies": [
            {"id": "B1", "xyxy": [0, 0, 30, 30]},
            {"id": "B2", "xyxy": [0, 0, 25, 25], "uncertain": True},
        ],
        "heads": [{"id": "H1", "xyxy": [5, 5, 20, 20], "body_id": "B1"}],
        "tags": [{"id": "T1", "xyxy": [5, 5, 8, 8], "body_id": "B1"}],
    }
    first = predict(row)
    row["tags"][0]["body_id"] = "B2"
    row["heads"][0]["body_id"] = "B2"
    assert predict(row) == first
    assert first["tags"][0]["body_id"] is None
    assert first["heads"]["H1"]["candidates"] == ["B1", "B2"]


def test_ambiguous_head_and_unknown_attachment_are_not_claimed_as_correct():
    assert (
        choices(
            [0, 0, 5, 5],
            [
                {"id": "H1", "xyxy": [0, 0, 10, 10]},
                {"id": "H2", "xyxy": [0, 0, 20, 20]},
            ],
        )["selected"]
        is None
    )
    assert outcome("B1", None) == "accepted_unverified"
    assert outcome("B1", "B1", uncertain=True) == "accepted_unverified"
    assert outcome(None, "B1") == "abstained"
