"""Score recorded online names from a separately frozen continuous reserved run."""

import argparse
import importlib.metadata
import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_sam_tracking import score
from video_assessment import annotations


def validate_freeze(evaluation, selection):
    if (
        evaluation["status"] != "FROZEN_EVALUATION"
        or selection["status"] != "FROZEN_SELECTION"
    ):
        raise ValueError("Draft reserved protocols cannot authorize scoring")
    if not evaluation["joint_development"]["tests_passed"] or any(
        evaluation["joint_development"][key] is None
        for key in ("execution_protocol_sha256", "run_sha256", "assessment_sha256")
    ):
        raise ValueError("Bind the completed joint development assessment first")
    keys = (
        "processing_fps",
        "first_processed_second",
        "last_processed_second",
        "scoring_fps",
        "score_windows",
        "seeded_cows",
        "named_cows",
        "anonymous_cows",
        "video_sha256",
        "source_annotations_sha256",
        "safe_annotations_sha256",
        "selected_development_protocol_sha256",
        "joint_development",
        "acceptance",
        "initialization",
        "policy",
        "method",
        "scoring_libraries",
    )
    if any(evaluation[key] != selection[key] for key in keys):
        raise ValueError("The method changed after the pre-input selection freeze")
    if any(
        evaluation["files"].get(path) != expected
        for path, expected in selection["files"].items()
    ):
        raise ValueError("The selected implementation bindings changed after freezing")
    if (
        evaluation["score_windows"] != [[1800, 2099], [2700, 2999]]
        or evaluation["first_processed_second"] != 0
        or evaluation["last_processed_second"] != 2999
        or evaluation["processing_fps"] != 2
        or evaluation["scoring_fps"] != 1
    ):
        raise ValueError("Reserved scope differs from the continuous protocol addendum")


def validate_timeline(value, run, clip):
    rate, end = run["processing_fps"], run["last_processed_second"]
    expected = [index / rate for index in range(end * rate + 1)]
    if (
        not value["complete"]
        or value["stop_reason"] is not None
        or value["provenance"]["smoke_frames"] is not None
        or len(value["frame_seconds"]) != len(expected)
        or [row["second"] for row in clip["rows"]] != expected
        or [row["second"] for row in value["frame_samples"]] != expected
        or [row["second"] for row in value["memory_samples"]] != expected
        or [row["second"] for row in value["timeline"]] != list(range(end + 1))
    ):
        raise ValueError("Reserved scoring requires the complete continuous sequence")
    for sampled, source in zip(value["frame_samples"], clip["rows"], strict=True):
        if (
            sampled["pixels_sha256"] != source["pixels_sha256"]
            or sampled["publisher_frame"] != source["publisher_frame"]
            or source["publisher_frame"]
            != round(source["second"] * clip["source_fps"]) + 1
        ):
            raise ValueError("Reserved output differs from its exact source frames")
    source = {row["second"]: row for row in clip["rows"]}
    known_slots = {
        index
        for index, cow in enumerate(run["seeded_cows"])
        if cow in run["named_cows"]
    }
    for row in value["timeline"]:
        slots = [box["track_id"] for box in row["boxes"]]
        names = row["named_track_ids"]
        if (
            len(slots) != len(set(slots))
            or not set(slots) <= set(range(len(run["seeded_cows"])))
            or len(names) != len(set(names))
            or not set(names) <= set(slots) & known_slots
            or row["publisher_frame"] != source[row["second"]]["publisher_frame"]
            or row["source_pixels_sha256"] != source[row["second"]]["pixels_sha256"]
        ):
            raise ValueError("Online names or integer-frame correspondence are invalid")


def pooled_naming(windows):
    counts = Counter()
    for row in windows.values():
        counts.update(row["naming_counts"])
    named = sum(
        counts[key]
        for key in ("correct_name", "wrong_name", "unknown_named", "unmatched_named")
    )
    return {
        "naming_counts": dict(counts),
        "known_coverage": counts["correct_name"] / counts["visible_known"],
        "conservative_precision": counts["correct_name"] / named if named else 0.0,
        "unknown_false_naming_rate": counts["unknown_named"]
        / counts["visible_unknown"],
        "pooling": "Sum disjoint-panel raw counts; neither gap frames nor an average of window percentages",
    }


def acceptance(metrics, thresholds):
    counts = metrics["naming_counts"]
    unknown = counts["unknown_named"] / counts["visible_unknown"]
    return (
        metrics["conservative_precision"]
        >= thresholds["minimum_conservative_precision"]
        and metrics["known_coverage"] >= thresholds["minimum_known_coverage"]
        and unknown <= thresholds["maximum_unknown_false_naming_rate"]
    )


def runtime_summary(value, rate):
    durations = np.asarray(value["frame_seconds"])
    steady = durations[1:]
    return {
        "elapsed_seconds": value["elapsed_seconds"],
        "initialization_seconds": value["initialization_seconds"],
        "processed_frames": len(durations),
        "mean_seconds_per_input": float(durations.mean()),
        "p95_seconds_per_input": float(np.quantile(durations, 0.95)),
        "p99_seconds_per_input": float(np.quantile(durations, 0.99)),
        "fraction_above_input_interval": float((durations > 1 / rate).mean()),
        "mean_within_input_budget": bool(durations.mean() <= 1 / rate),
        "steady_after_first_input": {
            "processed_frames": len(steady),
            "mean_seconds_per_input": float(steady.mean()),
            "p95_seconds_per_input": float(np.quantile(steady, 0.95)),
            "p99_seconds_per_input": float(np.quantile(steady, 0.99)),
            "fraction_above_input_interval": float((steady > 1 / rate).mean()),
        },
        "peak_observed_driver_bytes": max(
            row["mps_driver_bytes"] for row in value["memory_samples"]
        ),
        "peak_observed_rss_bytes": max(
            row["process_peak_rss_bytes"] for row in value["memory_samples"]
        ),
        "peak_observed_driver_before_reclaim_bytes": max(
            row["mps_driver_before_reclaim_bytes"] for row in value["memory_samples"]
        ),
        "maximum_working_tokens": max(
            row["working_tokens"] for row in value["memory_samples"]
        ),
        "maximum_long_term_tokens": max(
            row["long_term_tokens"] for row in value["memory_samples"]
        ),
        "model_metadata": value["model_metadata"],
    }


def validate_execution(value, run, evaluation):
    """The declared selection and actual GPU execution must agree."""
    method = evaluation["method"]
    if any(
        run[key] != expected
        for key, expected in method.items()
        if key != "corroborator"
    ) or any(
        run["corroborator"][key] != expected
        for key, expected in method["corroborator"].items()
    ):
        raise ValueError("Execution changed the method selected before reserved input")
    metadata = value["model_metadata"]
    if (
        metadata["cutie_device"] not in ("mps", "mps:0")
        or metadata["cutie_dtype"] != "torch.float32"
        or metadata["yolo_device"] not in ("mps", "mps:0")
        or metadata["yolo_fp16"] is not True
    ):
        raise ValueError("Reserved execution must use actual MPS with FP32/FP16")
    if value["provenance"]["source_commit"] != method["source_commit"]:
        raise ValueError("The actual video tracker revision differs from selection")


def load_inputs(args):
    evaluation, selection, run, value, clip = [
        json.loads(path.read_text())
        for path in (
            args.evaluation_protocol,
            args.selection_plan,
            args.run_protocol,
            args.streaming,
            args.sampled_manifest,
        )
    ]
    validate_freeze(evaluation, selection)
    if any(
        importlib.metadata.version(name) != version
        for name, version in evaluation["scoring_libraries"].items()
    ):
        raise ValueError("Installed scoring libraries differ from the frozen selection")
    for path, expected in evaluation["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Changed frozen reserved input: {path}")
    for path, key in (
        (args.selection_plan, "selection_plan_sha256"),
        (args.run_protocol, "execution_protocol_sha256"),
        (args.sampled_manifest, "sampled_manifest_sha256"),
        (args.annotations, "safe_annotations_sha256"),
        (args.source_pickle, "source_annotations_sha256"),
    ):
        if digest(path) != evaluation[key]:
            raise ValueError(f"Unexpected reserved source binding: {key}")
    if (
        value["provenance"]["protocol_sha256"] != digest(args.run_protocol)
        or value["provenance"]["libraries"] != run["libraries"]
        or [row["cow"] for row in value["provenance"]["seed_prompts"]]
        != evaluation["seeded_cows"]
        or clip["contract"]["video_sha256"] != evaluation["video_sha256"]
        or any(
            run[key] != evaluation[key]
            for key in (
                "processing_fps",
                "last_processed_second",
                "seeded_cows",
                "named_cows",
            )
        )
    ):
        raise ValueError("Inference differs from the reserved source and method")
    validate_execution(value, run, evaluation)
    validate_timeline(value, run, clip)
    return evaluation, run, value, clip


def score_recorded(value, records, clip, run, window):
    """Evaluate emitted names; never recreate policy decisions from later evidence."""
    return score(
        value,
        records,
        clip,
        {**run, "score_seconds": window},
        value["provenance"]["seed_prompts"],
        name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "evaluation-protocol",
        "selection-plan",
        "run-protocol",
        "streaming",
        "sampled-manifest",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    evaluation, run, value, clip = load_inputs(args)
    records, _ = annotations(args)
    windows = {
        str(window[0]): score_recorded(value, records, clip, run, window)
        for window in evaluation["score_windows"]
    }
    pooled = pooled_naming(windows)
    report = {
        "scope": evaluation["scope"],
        "conditions": windows,
        "pooled": pooled,
        "acceptance": {
            key: acceptance(row, evaluation["acceptance"])
            for key, row in {**windows, "pooled": pooled}.items()
        },
        "observed_panel_ranges": {
            key: [
                min(row[key] for row in windows.values()),
                max(row[key] for row in windows.values()),
            ]
            for key in ("known_coverage", "conservative_precision")
        },
        "uncertainty": evaluation["uncertainty"],
        "runtime": runtime_summary(value, run["processing_fps"]),
        "input_sha256": {
            key: digest(path) for key, path in vars(args).items() if key != "output"
        },
        "scorer_sha256": digest(Path(__file__)),
    }
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
