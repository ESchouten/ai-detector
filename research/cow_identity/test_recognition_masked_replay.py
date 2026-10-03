"""Behavioral boundaries of the new masked appearance diagnostic."""

import numpy as np
import pytest
from recognition_masked_replay import predict_panel, score_panel

from aidetector.domain.models import BoundingBox, IdentityMatch


def manifest(frames):
    rows, metadata, vectors = [], [], []
    for second, observations in enumerate(frames):
        indices = []
        for track, vector, box in observations:
            indices.append(len(rows))
            rows.append({"track_id": track, "box": box, "second": second})
            vectors.append(vector)
        metadata.append({"second": second, "rows": indices})
    return {"frames": metadata, "rows": rows}, np.asarray(vectors, dtype=np.float32)


def names(result):
    return [[box.identity.identity_id for box in row["boxes"]] for row in result]


def test_anonymous_slot_can_name_any_gallery_animal_without_seed_protection():
    features, vectors = manifest([[(91, [0.0, 1.0], [100, 100, 200, 200])]] * 3)
    result = predict_panel(
        features, vectors, (("1", "first"), ("2", "second")), np.eye(2), 0, 2
    )
    assert names(result) == [[None], [None], ["2"]]


def test_cached_feature_cannot_be_reused_as_new_evidence_at_a_different_second():
    features, vectors = manifest([[(91, [0.0, 1.0], [100, 100, 200, 200])]] * 3)
    features["frames"][2]["rows"] = [1]
    with pytest.raises(ValueError, match="belong uniquely"):
        predict_panel(
            features, vectors, (("1", "first"), ("2", "second")), np.eye(2), 0, 2
        )


def test_conflicting_crops_reset_both_tracks_before_three_new_agreements():
    one = [(91, [1.0, 0.0], [100, 100, 200, 200])]
    collision = [*one, (7, [1.0, 0.0], [150, 100, 250, 200])]
    features, vectors = manifest([one] * 3 + [collision] + [one] * 3)
    result = predict_panel(
        features, vectors, (("1", "first"), ("2", "second")), np.eye(2), 0, 6
    )
    assert names(result) == [[None], [None], ["1"], [None, None], [None], [None], ["1"]]


def test_missing_or_clipped_observation_cannot_bridge_temporal_agreement():
    one = [(7, [1.0, 0.0], [100, 100, 200, 200])]
    clipped = [(7, [1.0, 0.0], [0, 100, 100, 200])]
    features, vectors = manifest([one, one, [], one, one, clipped, one, one, one])
    result = predict_panel(
        features, vectors, (("1", "first"), ("2", "second")), np.eye(2), 0, 8
    )
    assert names(result) == [
        [None],
        [None],
        [],
        [None],
        [None],
        [None],
        [None],
        [None],
        ["1"],
    ]


def test_scoring_retains_missed_known_unknown_named_and_unmatched_named_animals():
    records = {
        "frame_id": np.array([1, 1, 1]),
        "cow_id": np.array([1, 7, 2]),
        "x_center": np.array([150, 350, 550]) / 800,
        "y_center": np.array([150, 150, 150]) / 600,
        "width": np.array([100, 100, 100]) / 800,
        "height": np.array([100, 100, 100]) / 600,
    }
    result = score_panel(
        [
            {
                "second": 0,
                "eligible": [True, True, True],
                "boxes": [
                    BoundingBox(
                        *box, "cow", 1.0, index, identity=IdentityMatch(name, name, 0.9)
                    )
                    for index, (box, name) in enumerate(
                        [
                            ([100, 100, 200, 200], "1"),
                            ([300, 100, 400, 200], "2"),
                            ([100, 300, 200, 400], "2"),
                        ]
                    )
                ],
            }
        ],
        records,
    )
    assert result["counts"]["visible_known"] == 2
    assert result["counts"]["missed_annotations"] == 1
    assert result["counts"]["unknown_named"] == 1
    assert result["counts"]["unmatched_named"] == 1
    assert result["known_coverage"] == 0.5
    assert result["conservative_named_precision"] == 1 / 3
    assert result["unknown_false_naming_rate"] == 1
    assert result["per_cow"] == {
        "1": {"visible": 1, "correctly_named": 1, "coverage": 1.0},
        "2": {"visible": 1, "correctly_named": 0, "coverage": 0.0},
    }
