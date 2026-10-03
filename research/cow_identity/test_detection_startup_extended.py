import copy
import json
from types import SimpleNamespace

import detection_startup_extended as experiment
import pytest
from detection_startup_extended import anchors_from_report, gate_names, prefix_parity


def test_initial_labels_follow_actual_startup_order_and_keep_unknown_slots():
    cows = [6, 5, 3, 4, 1, 7, 2, 8]
    report = {"initial": {"geometry_anchors": dict(enumerate(cows))}}
    anchors = anchors_from_report(report, list("ABCDEFGH"))
    assert [row["cow"] for row in anchors] == cows
    assert [row["anonymous_label"] for row in anchors if row["cow"] <= 6] == list(
        "ABCDEG"
    )
    report["initial"]["geometry_anchors"][7] = 7
    with pytest.raises(ValueError, match="unique"):
        anchors_from_report(report, list("ABCDEFGH"))


def test_name_gate_uses_fixed_slots_quality_reciprocal_and_stable_conflicts():
    frame = {
        "boxes": [{"track_id": i} for i in range(8)],
        "objects": [{"track_id": i, "p10_probability": 0.8} for i in range(8)],
        "reciprocal_pairs": [{"track_id": i, "proposal_index": i} for i in range(7)],
        "conflicted_ids": [2],  # Stable1-based ID2 is zero-based slot1.
    }
    frame["objects"][3]["p10_probability"] = 0.69
    assert gate_names(frame, {0, 1, 2, 3, 4, 6}, 0.7) == [0, 2, 4, 6]
    assert len(frame["boxes"]) == 8  # Unknown/weak/unpaired animals are retained.


def prefix_fixture():
    samples = [
        {"second": i / 2, "publisher_frame": i * 10 + 1, "pixels_sha256": str(i)}
        for i in range(241)
    ]
    rows = [
        {
            "second": i,
            "mask_sha256": str(i),
            "boxes": [{"track_id": 0}],
            "objects": [{"track_id": 0, "p10_probability": 0.8}],
            "reciprocal_pairs": [{"track_id": 0, "proposal_index": 0}],
            "conflicted_ids": [],
            "named_track_ids": [],
            "raw_detector_boxes": [],
        }
        for i in range(121)
    ]
    old = {
        "complete": True,
        "frame_samples": samples,
        "timeline": rows,
        "config": {"memory": 5},
        "model_metadata": {"device": "mps"},
        "quarantine_events": [],
    }
    new = copy.deepcopy(old)
    for row in new["timeline"]:
        row["named_track_ids"] = [0]
    protocol = {
        "initial_anchors": [{"track_id": 0, "cow": 6}],
        "naming": {"minimum_p10": 0.7},
    }
    return old, new, protocol


def test_prefix_permits_only_predeclared_online_names_not_changed_evidence():
    old, new, protocol = prefix_fixture()
    assert prefix_parity(old, new, protocol)["exact_except_predeclared_names"]
    new["timeline"][7]["objects"][0]["p10_probability"] = 0.9
    result = prefix_parity(old, new, protocol)
    assert not result["exact_except_predeclared_names"]
    assert result["differences"] == [{"second": 7, "fields": ["objects"]}]


def test_prefix_rejects_extra_name_and_missing_half_second_source():
    old, new, protocol = prefix_fixture()
    new["timeline"][11]["named_track_ids"].append(6)
    assert prefix_parity(old, new, protocol)["differences"] == [
        {"second": 11, "fields": ["fixed_name_gate"]}
    ]
    new["frame_samples"].pop()
    with pytest.raises(ValueError):
        prefix_parity(old, new, protocol)


def test_prefix_retains_nonvisual_policy_and_actual_backend_parity():
    old, new, protocol = prefix_fixture()
    new["quarantine_events"] = [{"second": 120, "id": 1}, {"second": 121, "id": 2}]
    new["model_metadata"]["device"] = "cpu"
    result = prefix_parity(old, new, protocol)
    assert not result["exact_except_predeclared_names"]
    assert not result["model_config_equal"]
    assert not result["quarantine_events_equal"]


def test_failed_prefix_is_saved_without_reading_truth_or_producing_scores(
    tmp_path, monkeypatch
):
    old, new, protocol = prefix_fixture()
    new["timeline"][12]["mask_sha256"] = "changed"
    recipe = tmp_path / "protocol.json"
    recipe.write_text("{}")
    protocol["libraries"] = {}
    new["provenance"] = {
        "protocol_sha256": experiment.digest(recipe),
        "libraries": {},
        "seed_prompts": [],
    }
    (tmp_path / "streaming.json").write_text(json.dumps(new))
    original = tmp_path / "original.json"
    original.write_text(json.dumps(old))
    monkeypatch.setattr(experiment, "STARTUP_RUN", original)
    # File/pixel validation is a separate already-tested boundary; retain the
    # actual public prefix comparison here to exercise this scorer's fail gate.
    monkeypatch.setattr(
        experiment,
        "checked",
        lambda _: (protocol, {"height": 10, "width": 10}, None, {"prompts": []}, {}),
    )
    monkeypatch.setattr(experiment, "validate_timeline", lambda *_: None)
    monkeypatch.setattr(experiment, "verify_geometry", lambda *_: None)

    def unread_truth():
        raise AssertionError("A failed prefix must not open annotation arrays")

    monkeypatch.setattr(experiment, "exposed_truth", unread_truth)
    report = tmp_path / "report.json"
    experiment.assess(SimpleNamespace(protocol=recipe, output=tmp_path, report=report))
    result = json.loads(report.read_text())
    assert result["status"] == "FAILED_PREFIX_PARITY"
    assert result["scores"] is None
    assert result["prefix_parity"]["differences"] == [
        {"second": 12, "fields": ["mask_sha256"]}
    ]
