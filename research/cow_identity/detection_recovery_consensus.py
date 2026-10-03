"""Replay the fixed recovered-conflict and reciprocal-confirmation conjunction."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_actual_audit import lcc_timeline
from detection_actual_score import load_inputs
from detection_box_consensus import correspondences
from detection_cutie_variants import probability_gate
from detection_sam_tracking import score
from video_assessment import annotations


def execute(args):
    frozen = json.loads(args.conjunction_protocol.read_text())
    for path, expected in frozen["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Changed frozen conjunction input: {path}")
    protocol, rules, original, detections, clip = load_inputs(args)
    recovery = json.loads(args.recovery_report.read_text())
    value = lcc_timeline(original, args.propagation.parent, clip)
    conflicts = recovery["conflicted_ids_by_second"]
    if sorted(map(int, conflicts)) != list(
        range(protocol["last_processed_second"] + 1)
    ):
        raise ValueError("Recovered conflict state must cover every source second")
    proposals = {row["second"]: row["boxes"] for row in detections["timeline"]}
    accepted = {"maximum_iou_baseline": {}, "fixed_reciprocal_conjunction": {}}
    for frame in value["timeline"]:
        confirmed, reciprocal = correspondences(
            frame["boxes"], proposals[frame["second"]], frozen["minimum_iou"]
        )
        for name, pairs in zip(accepted, (confirmed, reciprocal), strict=True):
            accepted[name][frame["second"]] = {
                frame["boxes"][index]["track_id"] for index in pairs
            }
    records, _ = annotations(args)
    quality = probability_gate(rules["base"]["minimum_p10_probability"])
    conditions = {}
    for name, confirmations in accepted.items():

        def allowed(frame, box, current=confirmations):
            return (
                quality(frame, box)
                and box.track_id + 1 not in conflicts[str(frame["second"])]
                and box.track_id in current[frame["second"]]
            )

        conditions[name] = {
            str(window[0]): score(
                value,
                records,
                clip,
                {**protocol, "score_seconds": window},
                value["provenance"]["seed_prompts"],
                name_allowed=allowed,
            )
            for window in protocol["comparison_windows"]
        }
    if any(
        result != recovery["conditions"]["corroborated_recovery"][window]["metrics"]
        for window, result in conditions["maximum_iou_baseline"].items()
    ):
        raise ValueError(
            "Conjunction must reproduce the frozen recovery baseline exactly"
        )
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.conjunction_protocol),
        "conditions": conditions,
        "baseline_exactly_reproduced": True,
        "unknown_false_naming_rates": {
            name: {
                window: row["naming_counts"]["unknown_named"]
                / row["naming_counts"]["visible_unknown"]
                for window, row in rows.items()
            }
            for name, rows in conditions.items()
        },
        "selection": "One frozen conjunction; no threshold search, no reserved frames and no automatic promotion",
    }
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
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
        "recovery-report",
        "conjunction-protocol",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    execute(parser.parse_args())
