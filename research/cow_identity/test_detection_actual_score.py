"""Actual initialization scoring cannot reuse shifted or incomplete detector outputs."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from benchmark import digest
from detection_actual_score import validate_provenance, validate_sequences
from test_detection_cutie_cadence import inputs


def sequences():
    value, protocol, clip, rules = inputs()
    for row in clip["rows"]:
        row["pixels_sha256"] = f"pixels-{row['publisher_frame']}"
    detections = {
        "complete": True,
        "timeline": [
            {
                "second": row["second"],
                "publisher_frame": row["publisher_frame"],
                "source_pixels_sha256": row["pixels_sha256"],
                "boxes": [],
            }
            for row in clip["rows"]
            if float(row["second"]).is_integer()
        ],
    }
    return value, detections, protocol, clip, rules


def test_empty_detector_frames_are_valid_but_omitted_or_duplicated_frames_are_not():
    arguments = sequences()
    validate_sequences(*arguments)
    missing = deepcopy(arguments)
    missing[1]["timeline"].pop(1)
    with pytest.raises(ValueError, match="every frozen source timestamp"):
        validate_sequences(*missing)
    duplicate = deepcopy(arguments)
    duplicate[1]["timeline"][1] = duplicate[1]["timeline"][0]
    with pytest.raises(ValueError, match="every frozen source timestamp"):
        validate_sequences(*duplicate)


def test_matching_timestamp_with_different_pixels_or_offset_cannot_corroborate():
    arguments = sequences()
    arguments[1]["timeline"][1]["source_pixels_sha256"] = "neighboring-frame"
    with pytest.raises(ValueError, match="same source pixels"):
        validate_sequences(*arguments)
    arguments = sequences()
    arguments[1]["timeline"][1]["publisher_frame"] -= 1
    with pytest.raises(ValueError, match="same source pixels"):
        validate_sequences(*arguments)


def test_incomplete_cutie_or_changed_seed_order_and_quarantine_are_not_scored():
    arguments = sequences()
    arguments[0]["complete"] = False
    with pytest.raises(ValueError, match="every frozen source timestamp"):
        validate_sequences(*arguments)
    arguments = sequences()
    arguments[0]["provenance"]["seed_prompts"].reverse()
    with pytest.raises(ValueError, match="Seed order"):
        validate_sequences(*arguments)
    arguments = sequences()
    arguments[4]["base"]["minimum_p10_probability"] = 0.5
    with pytest.raises(ValueError, match="fixed quarantine"):
        validate_sequences(*arguments)


def test_cpu_cutie_cannot_be_presented_as_the_frozen_metal_experiment(tmp_path):
    args = SimpleNamespace(
        protocol=tmp_path / "protocol.json", seed_manifest=tmp_path / "seeds.json"
    )
    args.protocol.write_text("{}")
    seeds = [{"cow": 1, "box": [0, 0, 10, 10]}]
    args.seed_manifest.write_text(
        json.dumps({"rows": [{"frame": 1, "prompts": seeds}]})
    )
    protocol = {
        "corroborator": {
            "runner_sha256": "runner",
            "model_sha256": "model",
            "settings": {},
        },
        "sampled_manifest_sha256": "manifest",
        "video_sha256": "video",
        "sampled_clip_sha256": "clip",
        "source_commit": "commit",
    }
    detections = {
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "runner_sha256": "runner",
            "model_sha256": "model",
            "sampled_manifest_sha256": "manifest",
            "video_sha256": "video",
            "settings": {},
        },
        "actual_device": "mps",
        "actual_fp16": True,
    }
    value = {
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "source_commit": "commit",
            "seed_prompts": seeds,
        },
        "parameter_dtype": "torch.float32",
        "actual_device": "mps:0",
    }
    clip = {"contract": {"video_sha256": "video"}, "clip_sha256": "clip"}
    validate_provenance(args, protocol, value, detections, clip)
    value["actual_device"] = "cpu"
    with pytest.raises(ValueError, match="inference precision"):
        validate_provenance(args, protocol, value, detections, clip)
