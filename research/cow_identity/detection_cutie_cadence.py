"""Compare a frozen Cutie input cadence using the unchanged quarantine policy."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_cutie_quarantine import compare, replay
from video_assessment import annotations


def validate_timeline(value, protocol, clip, rules):
    """Keep input cadence distinct from one-second scoring and quarantine history."""
    rate = protocol["processing_fps"]
    end = protocol["last_processed_second"]
    expected = [index / rate for index in range(end * rate + 1)]
    if (
        [row["second"] for row in clip["rows"]] != expected
        or clip["contract"]["protocol_sha256"] != protocol["clip_plan_sha256"]
        or any(
            row["publisher_frame"] != round(row["second"] * clip["source_fps"]) + 1
            for row in clip["rows"]
        )
    ):
        raise ValueError("Input frames do not follow the frozen source cadence")
    if (
        not value["complete"]
        or value["stop_reason"] is not None
        or len(value["frame_seconds"]) != len(expected)
        or [row["second"] for row in value["timeline"]] != list(range(end + 1))
    ):
        raise ValueError("Scoring requires complete inference and every integer second")
    if (
        rules["processed_seconds"] != [0, end]
        or list(rules["score_windows"].values()) != protocol["comparison_windows"]
        or protocol["quality_control"]["thresholds"]
        != [rules["base"]["minimum_p10_probability"]]
        or protocol["quality_control"]["box_variants"] != [rules["base"]["box_variant"]]
        or [seed["cow"] for seed in value["provenance"]["seed_prompts"]]
        != protocol["seeded_cows"]
    ):
        raise ValueError("Cadence comparison changed the frozen scoring policy")


def load_inputs(args):
    protocol = json.loads(args.protocol.read_text())
    rules = json.loads(args.quarantine_protocol.read_text())
    value = json.loads(args.propagation.read_text())
    clip = json.loads(args.sampled_manifest.read_text())
    if (
        digest(args.quarantine_protocol) != protocol["quarantine_protocol_sha256"]
        or digest(args.sampled_manifest) != protocol["sampled_manifest_sha256"]
        or digest(args.source_pickle) != protocol["source_annotations_sha256"]
        or value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or clip["contract"]["video_sha256"] != protocol["video_sha256"]
        or clip["clip_sha256"] != protocol["sampled_clip_sha256"]
    ):
        raise ValueError("Cadence source differs from its frozen protocol")
    validate_timeline(value, protocol, clip, rules)
    return value, protocol, clip, rules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "protocol",
        "quarantine-protocol",
        "sampled-manifest",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    value, protocol, clip, rules = load_inputs(args)
    records, _ = annotations(args)
    transformed, conflicts, events = replay(
        value,
        args.propagation.parent,
        clip,
        rules,
        range(1, len(protocol["seeded_cows"]) + 1),
    )
    results = compare(transformed, records, clip, protocol, rules, conflicts)
    report = {
        "scope": "Fixed cadence control on exposed footage, no quality sweep or reserved test",
        "processing_fps": protocol["processing_fps"],
        "quarantine_and_scoring_fps": 1,
        "protocol_sha256": digest(args.protocol),
        "quarantine_protocol_sha256": digest(args.quarantine_protocol),
        "propagation_sha256": digest(args.propagation),
        "sampled_manifest_sha256": digest(args.sampled_manifest),
        "annotations_sha256": digest(args.annotations),
        "runner_sha256": digest(Path(__file__)),
        "helpers_sha256": {
            name: digest(Path(__file__).with_name(name))
            for name in (
                "detection_cutie_quarantine.py",
                "detection_cutie_variants.py",
                "detection_sam_tracking.py",
            )
        },
        "conditions": results,
        "events": events,
        "conflicted_ids_by_second": conflicts,
        "elapsed_seconds": value["elapsed_seconds"],
        "processed_frames": len(value["frame_seconds"]),
        "peak_observed_mps_driver_bytes": value["peak_observed_mps_driver_bytes"],
    }
    write_json(args.output, report)
    print(json.dumps({"conditions": results, "events": events}))


if __name__ == "__main__":
    main()
