"""Score the frozen actual-seed Cutie pipeline with stateless corroboration."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_corroboration import maximum_iou, measure
from detection_cutie_quarantine import replay
from video_assessment import annotations


def validate_sequences(value, detections, protocol, clip, rules):
    """No shortened sequence, shifted frame or old tracker output may be scored."""
    end, rate = protocol["last_processed_second"], protocol["processing_fps"]
    seconds = list(range(end + 1))
    if (
        not value["complete"]
        or value["stop_reason"] is not None
        or not detections["complete"]
        or len(value["frame_seconds"]) != end * rate + 1
        or [row["second"] for row in value["timeline"]] != seconds
        or [row["second"] for row in detections["timeline"]] != seconds
    ):
        raise ValueError("Both predictors must finish every frozen source timestamp")
    if [row["second"] for row in clip["rows"]] != [
        index / rate for index in range(end * rate + 1)
    ] or any(
        row["publisher_frame"] != round(row["second"] * clip["source_fps"]) + 1
        for row in clip["rows"]
    ):
        raise ValueError("Source cadence or publisher frame alignment changed")
    source = {row["second"]: row for row in clip["rows"]}
    for row in detections["timeline"]:
        expected = source[row["second"]]
        if (
            row["publisher_frame"] != expected["publisher_frame"]
            or row["source_pixels_sha256"] != expected["pixels_sha256"]
        ):
            raise ValueError("Corroboration is not from the same source pixels")
    if (
        rules["processed_seconds"] != [0, end]
        or list(rules["score_windows"].values()) != protocol["comparison_windows"]
        or [rules["base"]["minimum_p10_probability"]]
        != protocol["quality_control"]["thresholds"]
        or [rules["base"]["box_variant"]] != protocol["quality_control"]["box_variants"]
        or [seed["cow"] for seed in value["provenance"]["seed_prompts"]]
        != protocol["seeded_cows"]
    ):
        raise ValueError("Seed order or fixed quarantine/scoring policy changed")


def validate_provenance(args, protocol, value, detections, clip):
    contract = detections["provenance"]
    expected = {
        "protocol_sha256": digest(args.protocol),
        "runner_sha256": protocol["corroborator"]["runner_sha256"],
        "model_sha256": protocol["corroborator"]["model_sha256"],
        "sampled_manifest_sha256": protocol["sampled_manifest_sha256"],
        "video_sha256": protocol["video_sha256"],
        "settings": protocol["corroborator"]["settings"],
    }
    if any(contract[key] != item for key, item in expected.items()):
        raise ValueError("Corroborator provenance differs from the frozen pipeline")
    seeds = json.loads(args.seed_manifest.read_text())["rows"][0]
    if (
        value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or value["provenance"]["source_commit"] != protocol["source_commit"]
        or value["provenance"]["seed_prompts"] != seeds["prompts"]
        or seeds["frame"] != 1
        or clip["contract"]["video_sha256"] != protocol["video_sha256"]
        or clip["clip_sha256"] != protocol["sampled_clip_sha256"]
        or detections["actual_device"] != "mps"
        or not detections["actual_fp16"]
        or value["actual_device"] not in ("mps", "mps:0")
        or value["parameter_dtype"] != "torch.float32"
    ):
        raise ValueError("Cutie source, actual seeds or inference precision changed")


def load_inputs(args):
    protocol, rules, value, detections, clip = [
        json.loads(path.read_text())
        for path in (
            args.protocol,
            args.quarantine_protocol,
            args.propagation,
            args.corroborator,
            args.sampled_manifest,
        )
    ]
    for path, expected in (
        (args.quarantine_protocol, protocol["quarantine_protocol_sha256"]),
        (args.sampled_manifest, protocol["sampled_manifest_sha256"]),
        (
            args.sampled_manifest.with_name("sampled.avi"),
            protocol["sampled_clip_sha256"],
        ),
        (args.seed_manifest, protocol["seed_manifest_sha256"]),
        (args.source_pickle, protocol["source_annotations_sha256"]),
        (
            Path(__file__).with_name("detection_cutie.py"),
            value["provenance"]["runner_sha256"],
        ),
    ):
        if digest(path) != expected:
            raise ValueError(f"Changed frozen pipeline input: {path}")
    validate_provenance(args, protocol, value, detections, clip)
    validate_sequences(value, detections, protocol, clip, rules)
    return protocol, rules, value, detections, clip


def evaluate(args, protocol, rules, value, detections, clip):
    # Recompute uncertainty from these masks, before accessing any truth annotations.
    changed, conflicts, events = replay(
        value,
        args.propagation.parent,
        clip,
        rules,
        range(1, len(protocol["seeded_cows"]) + 1),
    )
    detector_boxes = {row["second"]: row["boxes"] for row in detections["timeline"]}
    overlaps = {
        frame["second"]: {
            box["track_id"]: maximum_iou(box, detector_boxes[frame["second"]])
            for box in frame["boxes"]
        }
        for frame in changed["timeline"]
    }
    records, _ = annotations(args)
    quality = {"minimum_p10_probability": rules["base"]["minimum_p10_probability"]}
    quarantine = {
        "conflicted_ids_by_second": {str(key): val for key, val in conflicts.items()}
    }
    conditions = {
        str(window[0]): {
            name: measure(
                changed,
                records,
                clip,
                protocol,
                quality,
                quarantine,
                overlaps,
                window,
                threshold,
            )
            for name, threshold in (
                ("quarantine_only_diagnostic", None),
                ("frozen_pipeline", protocol["corroborator"]["minimum_iou"]),
            )
        }
        for window in protocol["comparison_windows"]
    }
    return {
        "scope": "Exposed development only; actual reviewed seeds and stateless YOLO are two changes",
        "conditions": conditions,
        "events": events,
        "conflicted_ids_by_second": conflicts,
        "maximum_iou_by_second_and_original_slot": overlaps,
        "corroborator_provenance": detections["provenance"],
        "corroborator_runtime": {
            key: detections[key]
            for key in (
                "actual_device",
                "actual_fp16",
                "class_names",
                "resolved_preprocessing",
            )
        },
        "cutie_provenance": value["provenance"],
        "cutie_runtime": {
            key: value[key] for key in ("actual_device", "parameter_dtype")
        },
        "cutie_elapsed_seconds": value["elapsed_seconds"],
        "corroborator_elapsed_seconds": detections["elapsed_seconds"],
        "processed_frames": len(value["frame_seconds"]),
        "peak_observed_mps_driver_bytes": value["peak_observed_mps_driver_bytes"],
        "combined_latency_caveat": "Separate processes/runs; concurrent throughput not measured",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "protocol",
        "quarantine-protocol",
        "corroborator",
        "sampled-manifest",
        "seed-manifest",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args, *load_inputs(args))
    report["input_sha256"] = {
        key: digest(path) for key, path in vars(args).items() if key != "output"
    }
    report["implementation_sha256"] = {
        name: digest(Path(__file__).with_name(name))
        for name in (
            Path(__file__).name,
            "detection_corroboration.py",
            "detection_cutie_quarantine.py",
            "detection_cutie_variants.py",
            "detection_sam_tracking.py",
            "video_assessment.py",
        )
    }
    write_json(args.output, report)
    print(json.dumps({"conditions": report["conditions"], "events": report["events"]}))


if __name__ == "__main__":
    main()
