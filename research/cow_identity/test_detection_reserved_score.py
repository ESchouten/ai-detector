"""Recorded names and held-out denominators cannot be silently rewritten."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from detection_reserved_score import (
    acceptance,
    pooled_naming,
    runtime_summary,
    score_recorded,
    validate_execution,
    validate_freeze,
    validate_timeline,
)

from aidetector.domain.models import BoundingBox


def synthetic_sequence():
    run = {
        "processing_fps": 2,
        "last_processed_second": 2,
        "seeded_cows": [1, 8],
        "named_cows": [1],
    }
    samples = [
        {
            "second": index / 2,
            "publisher_frame": index * 10 + 1,
            "pixels_sha256": f"pixels-{index}",
        }
        for index in range(5)
    ]
    clip = {"source_fps": 20, "rows": deepcopy(samples)}
    value = {
        "complete": True,
        "stop_reason": None,
        "provenance": {"smoke_frames": None},
        "frame_seconds": [0.1] * 5,
        "frame_samples": samples,
        "memory_samples": [{"second": row["second"]} for row in samples],
        "timeline": [
            {
                "second": int(row["second"]),
                "publisher_frame": row["publisher_frame"],
                "source_pixels_sha256": row["pixels_sha256"],
                "boxes": [{"track_id": 0}, {"track_id": 1}],
                "named_track_ids": [0],
            }
            for row in samples
            if row["second"].is_integer()
        ],
    }
    return value, run, clip


def test_incomplete_or_misaligned_input_cannot_reduce_the_denominator():
    arguments = synthetic_sequence()
    validate_timeline(*arguments)
    missing = deepcopy(arguments)
    missing[0]["timeline"].pop(1)
    with pytest.raises(ValueError, match="complete continuous"):
        validate_timeline(*missing)
    shifted = deepcopy(arguments)
    shifted[0]["frame_samples"][1]["pixels_sha256"] = "different-pixels"
    with pytest.raises(ValueError, match="exact source frames"):
        validate_timeline(*shifted)
    arguments[0]["provenance"]["smoke_frames"] = 5
    with pytest.raises(ValueError, match="complete continuous"):
        validate_timeline(*arguments)


def test_online_names_must_refer_to_present_original_known_slots():
    for names, slots in (([1], [0, 1]), ([0], [1]), ([0, 0], [0, 1]), ([], [900])):
        arguments = synthetic_sequence()
        arguments[0]["timeline"][1].update(
            named_track_ids=names, boxes=[{"track_id": slot} for slot in slots]
        )
        with pytest.raises(ValueError, match="Online names"):
            validate_timeline(*arguments)


def test_pooling_uses_all_raw_named_errors_including_unmatched_and_unknown():
    counts = {
        "correct_name": 1,
        "wrong_name": 1,
        "unknown_named": 1,
        "unmatched_named": 1,
        "visible_known": 2,
        "visible_unknown": 4,
    }
    second = {**counts, "correct_name": 9, "visible_known": 10}
    pooled = pooled_naming(
        {"first": {"naming_counts": counts}, "second": {"naming_counts": second}}
    )
    assert pooled["known_coverage"] == 10 / 12
    assert pooled["conservative_precision"] == 10 / 16
    assert pooled["unknown_false_naming_rate"] == 2 / 8
    assert pooled["known_coverage"] != (1 / 2 + 9 / 10) / 2
    assert not acceptance(
        pooled,
        {
            "minimum_conservative_precision": 0.99,
            "minimum_known_coverage": 0.6,
            "maximum_unknown_false_naming_rate": 0.01,
        },
    )


def selected_protocols():
    path = Path(__file__).with_name("detection_reserved_protocol.template.json")
    selection = json.loads(path.read_text())
    selection["status"] = "FROZEN_SELECTION"
    selection["joint_development"] = {
        "execution_protocol_sha256": "joint-protocol",
        "run_sha256": "joint-run",
        "assessment_sha256": "joint-assessment",
        "tests_passed": True,
    }
    evaluation = {**deepcopy(selection), "status": "FROZEN_EVALUATION"}
    return evaluation, selection


def test_draft_or_changed_method_cannot_authorize_reserved_scoring():
    evaluation, selection = selected_protocols()
    validate_freeze(evaluation, selection)
    evaluation["status"] = "DRAFT_NOT_AUTHORIZED"
    with pytest.raises(ValueError, match="Draft"):
        validate_freeze(evaluation, selection)
    evaluation, selection = selected_protocols()
    evaluation["method"]["recovery"]["consecutive_frames"] = 2
    with pytest.raises(ValueError, match="method changed"):
        validate_freeze(evaluation, selection)
    evaluation, selection = selected_protocols()
    evaluation["files"][next(iter(evaluation["files"]))] = "changed-weights"
    with pytest.raises(ValueError, match="implementation bindings"):
        validate_freeze(evaluation, selection)


def test_cpu_fallback_or_changed_precision_cannot_claim_metal_throughput():
    evaluation, _ = selected_protocols()
    run = deepcopy(evaluation["method"])
    value = {
        "provenance": {"source_commit": run["source_commit"]},
        "model_metadata": {
            "cutie_device": "mps:0",
            "cutie_dtype": "torch.float32",
            "yolo_device": "mps",
            "yolo_fp16": True,
        },
    }
    validate_execution(value, run, evaluation)
    for key, changed in (("cutie_device", "cpu"), ("yolo_fp16", False)):
        invalid = deepcopy(value)
        invalid["model_metadata"][key] = changed
        with pytest.raises(ValueError, match="actual MPS"):
            validate_execution(invalid, run, evaluation)
    run["corroborator"]["settings"]["conf"] = 0.3
    with pytest.raises(ValueError, match="changed the method"):
        validate_execution(value, run, evaluation)


def test_runtime_includes_slow_frames_and_observed_memory():
    value = {
        "frame_seconds": [0.1, 0.6],
        "elapsed_seconds": 1.0,
        "initialization_seconds": 0.3,
        "memory_samples": [
            {
                "mps_driver_bytes": driver,
                "mps_driver_before_reclaim_bytes": before,
                "process_peak_rss_bytes": rss,
                "working_tokens": working,
                "long_term_tokens": long_term,
            }
            for driver, before, rss, working, long_term in (
                (100, 100, 200, 10, 0),
                (300, 500, 220, 12, 20),
            )
        ],
        "model_metadata": {},
    }
    result = runtime_summary(value, 2)
    assert result["processed_frames"] == 2
    assert result["mean_seconds_per_input"] == 0.35
    assert result["fraction_above_input_interval"] == 0.5
    assert result["peak_observed_driver_bytes"] == 300
    assert result["peak_observed_rss_bytes"] == 220
    assert result["peak_observed_driver_before_reclaim_bytes"] == 500
    assert result["maximum_working_tokens"] == 12
    assert result["maximum_long_term_tokens"] == 20
    assert result["steady_after_first_input"]["p99_seconds_per_input"] == 0.6


def test_scoring_uses_emitted_names_and_keeps_rejected_boxes_in_coverage():
    records = {
        "frame_id": np.array([1, 1]),
        "cow_id": np.array([1, 7]),
        "x_center": np.array([0.1, 0.6]),
        "y_center": np.array([0.1, 0.1]),
        "width": np.array([0.2, 0.2]),
        "height": np.array([0.2, 0.2]),
    }
    value = {
        "provenance": {"seed_prompts": [{"cow": 1}, {"cow": 7}]},
        "timeline": [
            {
                "second": 0,
                "boxes": [
                    asdict(BoundingBox(0, 0, 20, 20, track_id=0)),
                    asdict(BoundingBox(50, 0, 70, 20, track_id=1)),
                ],
                "named_track_ids": [],
            }
        ],
    }
    clip = {"source_fps": 20, "width": 100, "height": 100}
    run = {"last_processed_second": 0, "named_cows": [1]}
    rejected = score_recorded(value, records, clip, run, [0, 0])
    value["timeline"][0]["named_track_ids"] = [0]
    named = score_recorded(value, records, clip, run, [0, 0])
    assert rejected["naming_counts"]["known_unnamed"] == 1
    assert rejected["known_coverage"] == 0
    assert named["naming_counts"]["correct_name"] == 1
    assert named["known_coverage"] == 1
    assert rejected["tracking"] == named["tracking"]
