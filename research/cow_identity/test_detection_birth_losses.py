"""Coverage attribution keeps missing geometry distinct from naming vetoes."""

from detection_birth_losses import frame_outcomes, summarize_rows


def frame():
    return {
        "second": 330,
        "boxes": [
            {
                "x1": 0,
                "y1": 0,
                "x2": 100,
                "y2": 100,
                "label": "cow",
                "confidence": 0.8,
                "track_id": 0,
            }
        ],
        "objects": [{"track_id": 0, "p10_probability": 0.6}],
        "named_track_ids": [],
        "conflicted_ids": [1],
        "reciprocal_pairs": [],
    }


def test_gate_failures_overlap_but_observation_is_counted_once():
    row = frame_outcomes(frame(), [{"cow": 1, "box": [0, 0, 100, 100]}])[1]
    assert row["reasons"] == ["low_p10", "no_reciprocal_detector", "quarantined"]
    result = summarize_rows([row])
    assert result["visible_known"] == 1
    assert sum(result["exclusive_reasons"].values()) == 1
    assert sum(result["overlapping_gate_counts"].values()) == 3


def test_anonymous_geometry_cannot_supply_an_original_name():
    value = frame()
    value["boxes"][0]["track_id"] = 6
    truth = [
        {"cow": 1, "box": [0, 0, 100, 100]},
        {"cow": 2, "box": [200, 200, 300, 300]},
    ]
    rows = frame_outcomes(value, truth)
    assert rows[1]["reasons"] == ["matched_different_slot"]
    assert rows[2]["reasons"] == ["no_localization_match"]


def test_exact_boundary_p10_can_name_only_with_all_other_gates():
    value = frame()
    value.update(
        named_track_ids=[0],
        conflicted_ids=[],
        reciprocal_pairs=[{"track_id": 0, "proposal_index": 0}],
    )
    value["objects"][0]["p10_probability"] = 0.7
    row = frame_outcomes(value, [{"cow": 1, "box": [0, 0, 100, 100]}])[1]
    assert row["correct"] and row["reasons"] == []
