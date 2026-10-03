"""Check causal identity vetoes, frozen evidence and unchanged naming penalties."""

from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest
from benchmark import digest, write_json
from cutie_appearance import (
    allowed_names,
    appearance_evidence,
    choose,
    measure,
    predicted_timeline,
    read_features,
    validate_features,
)

from aidetector.domain.models import BoundingBox

CONDITION = {
    "minimum_p10_probability": 0.7,
    "minimum_own_similarity": 0.4,
    "minimum_own_minus_other": 0.05,
    "consecutive_passes": 3,
}


def features_at(times, tracks):
    rows, frames = [], []
    for second, visible in zip(times, tracks, strict=True):
        indices = []
        for track in visible:
            indices.append(len(rows))
            rows.append(
                {
                    "second": second,
                    "track_id": track,
                    "box": [1, 1, 9, 9],
                    "p10_probability": 0.7,
                    "mask_sha256": f"mask-{second}",
                }
            )
        frames.append({"second": second, "rows": indices})
    return {"rows": rows, "frames": frames}


def test_seed_evidence_uses_best_own_reference_but_never_guesses_a_new_name():
    rows = [{"track_id": 0}, {"track_id": 1}, {"track_id": 2}]
    references = [{"cow": 1}, {"cow": 1}, {"cow": 2}]
    gallery = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
    queries = np.array([[0.8, 0.6], [1, 0], [1, 0]], dtype=np.float32)
    result = appearance_evidence(
        rows,
        queries,
        references,
        gallery,
        [{"cow": 1}, {"cow": 2}, {"cow": 7}],
        [1, 2],
    )
    assert result[0]["own_similarity"] == pytest.approx(1)
    assert result[0]["own_minus_other"] == pytest.approx(0.4)
    assert result[1] == {"own_similarity": 0, "own_minus_other": -1}
    assert (
        result[2] is None
    )  # Anonymous seed matches a cow strongly, but stays anonymous.


def test_agreement_is_causal_and_resets_after_failure_missing_slot_and_time_gap():
    features = features_at(
        [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11],
        [
            [0, 1],
            [0, 1],
            [0, 1],
            [0],
            [0, 1],
            [0, 1],
            [0, 1],
            [0, 1],
            [0, 1],
            [0, 1],
            [0, 1],
        ],
    )
    evidence = [
        {"own_similarity": 0.4, "own_minus_other": 0.05} for _ in features["rows"]
    ]
    # At second3, appearance contradicts slot0. Slot1 is absent entirely.
    index = features["frames"][3]["rows"][0]
    evidence[index] = {"own_similarity": 0.39, "own_minus_other": 0.2}
    allowed = allowed_names(features, evidence, CONDITION, [0, 11])
    assert allowed == {(second, track) for second in (2, 6, 7, 11) for track in (0, 1)}
    # The same continuous stream keeps legitimate past evidence at a score boundary.
    assert allowed_names(features, evidence, CONDITION, [10, 11]) == {(11, 0), (11, 1)}
    evidence[-1] = None
    assert (11, 1) not in allowed_names(features, evidence, CONDITION, [0, 11])


def test_incomplete_duplicate_or_mask_mismatched_features_cannot_select_a_policy():
    features = features_at([330, 331], [[0], [0]])
    propagation = {
        "timeline": [
            {
                "second": row["second"],
                "mask_sha256": row["mask_sha256"],
                "objects": [{"track_id": 0, "p10_probability": 0.7}],
            }
            for row in features["rows"]
        ]
    }
    protocol = {"feature_windows": [[330, 331]]}
    validate_features(features, propagation, protocol, 100, 100)
    for times in ([330], [330, 330], [331, 330], [330, 331, 332]):
        broken = features_at(times, [[0] for _ in times])
        with pytest.raises(ValueError, match="timestamp"):
            validate_features(broken, propagation, protocol, 100, 100)
    broken = deepcopy(features)
    broken["rows"][0]["mask_sha256"] = "different-mask"
    with pytest.raises(ValueError, match="original mask"):
        validate_features(broken, propagation, protocol, 100, 100)
    broken = deepcopy(features)
    broken["rows"].append(dict(broken["rows"][0]))
    broken["frames"][0]["rows"].append(2)
    with pytest.raises(ValueError, match="every observation"):
        validate_features(broken, propagation, protocol, 100, 100)


def test_feature_file_hash_and_finite_normalized_vectors_are_required(tmp_path):
    np.savez_compressed(
        tmp_path / "vectors.npz", vectors=np.array([[1, 0]], dtype=np.float32)
    )
    manifest = {"rows": [{}], "vectors_sha256": digest(tmp_path / "vectors.npz")}
    write_json(tmp_path / "manifest.json", manifest)
    assert read_features(tmp_path)[1].shape == (1, 2)
    np.savez_compressed(
        tmp_path / "vectors.npz", vectors=np.array([[np.nan, 0]], dtype=np.float32)
    )
    with pytest.raises(ValueError, match="hash"):
        read_features(tmp_path)
    manifest["vectors_sha256"] = digest(tmp_path / "vectors.npz")
    write_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="normalized"):
        read_features(tmp_path)


def test_rejected_names_keep_all_boxes_misses_unknowns_and_unmatched_penalty():
    features = features_at([0], [[0, 1, 6]])
    features["rows"][0]["box"] = [0, 0, 10, 10]
    features["rows"][1]["box"] = [40, 0, 50, 10]  # Named box has no truth match.
    features["rows"][2]["box"] = [60, 0, 70, 10]  # Anonymous slot sees unknown cow7.
    seeds = [{"cow": cow} for cow in range(1, 9)]
    propagation = {
        "provenance": {"seed_prompts": seeds},
        "timeline": [
            {"second": 0, "boxes": [asdict(BoundingBox(0, 0, 99, 99, track_id=0))]}
        ],
    }
    value = predicted_timeline(propagation, features)
    assert len(value["timeline"][0]["boxes"]) == 3
    assert propagation["timeline"][0]["boxes"][0]["x2"] == 99
    records = {
        "frame_id": np.ones(3),
        "cow_id": np.array([1, 2, 7]),
        "x_center": np.array([0.05, 0.25, 0.65]),
        "y_center": np.full(3, 0.05),
        "width": np.full(3, 0.1),
        "height": np.full(3, 0.1),
    }
    evidence = [{"own_similarity": 0.8, "own_minus_other": 0.1}] * 2 + [None]
    result = measure(
        value,
        features,
        evidence,
        {**CONDITION, "consecutive_passes": 1},
        [0, 0],
        records,
        {"source_fps": 20, "width": 100, "height": 100},
        {"last_processed_second": 0, "named_cows": [1, 2, 3, 4, 5, 6]},
    )
    counts = result["metrics"]["naming_counts"]
    assert counts["visible_known"] == 2
    assert counts["correct_name"] == counts["unmatched_named"] == 1
    assert counts["unknown_named"] == 0
    assert result["metrics"]["known_coverage"] == 0.5
    assert result["metrics"]["conservative_precision"] == 0.5
    vetoed = measure(
        value,
        features,
        evidence,
        {**CONDITION, "consecutive_passes": 1},
        [0, 0],
        records,
        {"source_fps": 20, "width": 100, "height": 100},
        {"last_processed_second": 0, "named_cows": [1, 2, 3, 4, 5, 6]},
        blocked_names={(0, 1)},
    )
    assert vetoed["metrics"]["tracking"] == result["metrics"]["tracking"]
    assert vetoed["metrics"]["known_coverage"] == 0.5
    assert vetoed["metrics"]["conservative_precision"] == 1


def test_selection_never_promotes_inaccurate_or_useless_conditions():
    def result(coverage, precision, unknown=0, **condition):
        return {
            "condition": {**CONDITION, **condition},
            "metrics": {
                "known_coverage": coverage,
                "conservative_precision": precision,
            },
            "unknown_false_naming_rate": unknown,
        }

    simple = result(0.65, 0.995, consecutive_passes=1)
    candidates = [result(0.99, 0.98), result(0.8, 1, 0.02), result(0.65, 0.995), simple]
    assert choose(candidates) == {"selected": simple, "meets_all_gates": True}
    assert choose(candidates[:2])["selected"] is None
    assert choose([result(0.01, 1)])["meets_all_gates"] is False
