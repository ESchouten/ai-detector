"""End-to-end evaluation must not hide missed cows or named unmatched boxes."""

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from recognition_temporal import smoothed_scores, temporal_names
from scoring import Scores
from tracked_experiment import (
    PROTOCOL,
    calibrate_real_tracks,
    select_references,
    summarize,
    validate_gallery,
    validate_panel,
    validate_representation,
)


def test_fixed_gallery_rejects_query_references_and_changed_source(tmp_path):
    from benchmark import digest

    manifest = {"rows": [{"cow": cow, "panel": "enrollment"} for cow in range(1, 7)]}
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest))
    selection = tmp_path / "selection.json"
    chosen = {
        "source_manifest_sha256": digest(source),
        "rows": list(range(6)),
        "selection": "fixed early photos",
    }
    selection.write_text(json.dumps(chosen))
    args = SimpleNamespace(gallery=tmp_path, gallery_selection=selection)
    indexes, _ = select_references(args, manifest, np.eye(6))
    assert indexes.tolist() == list(range(6))
    manifest["rows"][0]["panel"] = "development"
    with pytest.raises(ValueError, match="early photos"):
        select_references(args, manifest, np.eye(6))
    source.write_text("different source")
    with pytest.raises(ValueError, match="another gallery"):
        select_references(args, manifest, np.eye(6))


def test_coverage_includes_missed_cows_and_precision_reports_unmatched_names():
    manifest = {
        "rows": [{"truth": 1}, {"truth": None}, {"truth": 7}],
        "frames": [{"truth": [{"cow": cow} for cow in (1, 2, 7, 8)]}],
    }
    result = summarize(manifest, np.array([1, 2, 3]))
    assert result["known_coverage"] == 0.5
    assert result["precision_on_matched"] == 0.5
    assert result["precision_lower_bound"] == 1 / 3
    assert result["unknown_false_acceptance_rate"] == 0.5
    assert result["counts"]["missed_annotations"] == 2
    assert result["counts"]["unmatched_named"] == 1
    assert result["per_cow"]["2"]["visible"] == 1
    assert result["per_cow"]["2"]["matched"] == 0


def test_rejecting_everything_is_zero_coverage_with_undefined_precision():
    manifest = {
        "rows": [],
        "frames": [{"truth": [{"cow": 1}, {"cow": 7}]}],
    }
    result = summarize(manifest, np.array([], dtype=int))
    assert result["known_coverage"] == 0
    assert result["precision_on_matched"] is None
    assert result["precision_lower_bound"] is None
    assert result["counts"]["missed_annotations"] == 2


def protocol_inputs():
    protocol = json.loads(PROTOCOL.read_text())
    gallery = {
        "contract": {
            "video_sha256": protocol["video_sha256"],
            "source_sha256": protocol["source_pickle_sha256"],
            "annotations_sha256": "verified-numeric-annotations",
            "enrolled_ids": protocol["known_ids"],
            "unknown_ids": protocol["unknown_ids"],
            "panels": {"enrollment": [0]},
            "encoder_fingerprint": "same-encoder",
        },
        "rows": [{"panel": "enrollment", "second": 0, "frame": 1, "cow": 1}],
    }
    panel = {
        "contract": {
            "encoder_fingerprint": "same-encoder",
            "tracking_provenance": {
                "video": protocol["video_sha256"],
                "annotations": "verified-numeric-annotations",
                "start": 330,
                "seconds": 300,
                "scoring_fps": 1,
            },
        },
        "frames": [
            {"second": second, "truth": [{"cow": 1}], "rows": [second - 330]}
            for second in range(330, 630)
        ],
        "rows": [
            {"second": second, "frame": second * 20 + 1, "track": 10, "truth": 1}
            for second in range(330, 630)
        ],
    }
    return protocol, gallery, panel


def test_complete_window_accepts_missed_detections_without_changing_denominator():
    protocol, gallery, panel = protocol_inputs()
    panel["frames"][-1]["rows"] = []
    panel["rows"].pop()
    validate_gallery(gallery, protocol)
    validate_panel(panel, gallery, "development", protocol)
    result = summarize(panel, np.ones(299, dtype=int))
    assert result["counts"]["missed_annotations"] == 1
    assert result["known_coverage"] == 299 / 300
    assert result["unknown_false_acceptance_rate"] is None


def test_missing_unknown_evidence_cannot_calibrate_a_successful_rejection_policy():
    _, _, panel = protocol_inputs()
    rows = [{**row, "track": 1} for row in panel["rows"]]
    assert calibrate_real_tracks(panel, (rows, temporal_scores(rows)), 0) == (
        1.01,
        1.01,
    )


@pytest.mark.parametrize("field", ["video", "annotations"])
def test_tracking_source_cannot_change_while_retaining_valid_window_metadata(field):
    protocol, gallery, panel = protocol_inputs()
    panel["contract"]["tracking_provenance"][field] = "another-source"
    with pytest.raises(ValueError, match="video or annotations"):
        validate_panel(panel, gallery, "development", protocol)


def test_derived_crops_keep_source_validation_and_compare_the_same_representation():
    protocol, gallery, panel = protocol_inputs()
    original = copy.deepcopy(gallery["contract"])
    gallery["contract"] = {
        "origin": original,
        "source_manifest_sha256": "original-gallery-manifest",
        "encoder_fingerprint": "gallery-cache-key",
        "representation_fingerprint": "same-masked-encoder",
    }
    panel["contract"].update(
        encoder_fingerprint="different-query-cache-key",
        representation_fingerprint="same-masked-encoder",
    )
    validate_gallery(gallery, protocol)
    validate_panel(panel, gallery, "development", protocol)
    validate_representation(gallery, panel, "development")
    gallery["contract"]["origin"]["source_sha256"] = "other-annotations"
    with pytest.raises(ValueError, match="frozen protocol"):
        validate_gallery(gallery, protocol)
    gallery["contract"]["origin"] = original | {
        "annotations_sha256": "other-conversion"
    }
    with pytest.raises(ValueError, match="video or annotations"):
        validate_panel(panel, gallery, "development", protocol)


def test_raw_and_derived_fingerprints_cannot_hide_different_transform_contracts():
    _, gallery, panel = protocol_inputs()
    validate_representation(gallery, panel, "development")
    panel["contract"]["encoder_fingerprint"] = "different-encoder"
    with pytest.raises(ValueError, match="different representations"):
        validate_representation(gallery, panel, "development")
    gallery["contract"]["representation_fingerprint"] = "masked"
    with pytest.raises(ValueError, match="mix derived and original"):
        validate_representation(gallery, panel, "development")
    panel["contract"]["representation_fingerprint"] = "aligned"
    with pytest.raises(ValueError, match="different representations"):
        validate_representation(gallery, panel, "development")


def test_extra_reserved_frame_is_rejected_even_when_start_metadata_is_correct():
    protocol, gallery, panel = protocol_inputs()
    panel["frames"].append({"second": 1800, "truth": [], "rows": []})
    with pytest.raises(ValueError, match="complete frozen window"):
        validate_panel(panel, gallery, "development", protocol)
    panel["frames"].pop()
    panel["rows"][0]["second"] = 1800
    with pytest.raises(ValueError):
        validate_panel(panel, gallery, "development", protocol)


def test_rows_cannot_be_omitted_repeated_or_assigned_to_another_source_frame():
    protocol, gallery, original = protocol_inputs()
    for indexes in ([], [0, 0], [1]):
        panel = copy.deepcopy(original)
        panel["frames"][0]["rows"] = indexes
        with pytest.raises(ValueError, match="exactly once"):
            validate_panel(panel, gallery, "development", protocol)
    original["rows"][0]["frame"] += 1
    with pytest.raises(ValueError, match="source frame"):
        validate_panel(original, gallery, "development", protocol)


def test_duplicate_prediction_cannot_claim_an_already_matched_cow():
    protocol, gallery, panel = protocol_inputs()
    panel["rows"].append({**panel["rows"][-1], "track": 11})
    panel["frames"][-1]["rows"].append(300)
    with pytest.raises(ValueError, match="one-to-one"):
        validate_panel(panel, gallery, "development", protocol)


@pytest.mark.parametrize("field", ["video_sha256", "source_sha256"])
def test_gallery_source_is_pinned_to_audited_publisher_data(field):
    protocol, gallery, _ = protocol_inputs()
    gallery["contract"][field] = "another-source"
    with pytest.raises(ValueError, match="frozen protocol"):
        validate_gallery(gallery, protocol)


def test_gallery_cannot_hide_unknown_or_final_window_examples_as_enrollment():
    protocol, original, _ = protocol_inputs()
    for mutation in ({"cow": 7}, {"second": 1800}, {"frame": 2}):
        gallery = copy.deepcopy(original)
        gallery["rows"][0].update(mutation)
        with pytest.raises(ValueError):
            validate_gallery(gallery, protocol)
    original["contract"]["panels"]["enrollment"].append(1800)
    with pytest.raises(ValueError, match="outside allowed windows"):
        validate_gallery(original, protocol)


def temporal_scores(rows):
    names = np.array([row["track"] or 1 for row in rows])
    return Scores(
        names,
        names,
        np.full(len(rows), 0.8),
        np.full(len(rows), 0.2),
        np.ones(len(rows), dtype=bool),
        np.zeros(len(rows)),
    )


@pytest.mark.parametrize("seconds", [[0, 0, 0], [0, 2, 1], [0, float("nan"), 2]])
def test_invalid_timestamps_cannot_accumulate_temporal_agreement(seconds):
    rows = [{"second": second, "track": 1, "cow": 1} for second in seconds]
    with pytest.raises(ValueError):
        temporal_names(rows, temporal_scores(rows), 0.65, 0.1, 30)
    with pytest.raises(ValueError):
        smoothed_scores(rows, np.ones((3, 2)), np.eye(2), np.array([1, 2]), 0.5, "none")


def test_distinct_tracks_share_frame_times_without_sharing_agreement():
    rows = [
        {"second": second, "track": track}
        for second in range(3)
        for track in (1, 2, None)
    ]
    np.testing.assert_array_equal(
        temporal_names(rows, temporal_scores(rows), 0.65, 0.1, 30),
        [0, 0, 0, 0, 0, 0, 1, 2, 0],
    )
