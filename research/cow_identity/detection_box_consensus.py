"""Compare original identity boxes with reciprocal detector geometry consensus."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_actual_score import load_inputs
from detection_corroboration import maximum_iou
from detection_cutie_quarantine import replay
from detection_cutie_variants import probability_gate
from detection_sam_tracking import score
from video_assessment import annotations

BOUNDS = ("x1", "y1", "x2", "y2")


def correspondences(boxes, proposals, minimum_iou):
    """Each independent proposal can confirm at most one original object slot."""
    if not boxes or not proposals:
        return {}, {}
    overlaps = [
        [maximum_iou(box, [proposal]) for proposal in proposals] for box in boxes
    ]
    best = {
        i: max(range(len(proposals)), key=lambda j: (overlaps[i][j], -j))
        for i in range(len(boxes))
    }
    reverse = {
        j: max(range(len(boxes)), key=lambda i: (overlaps[i][j], -i))
        for j in range(len(proposals))
    }
    confirmed = {i: j for i, j in best.items() if overlaps[i][j] >= minimum_iou}
    reciprocal = {i: j for i, j in confirmed.items() if reverse[j] == i}
    return confirmed, reciprocal


def prepare_conditions(value, detections, minimum_iou):
    """Transform geometry before loading truth; identities remain original slots."""
    proposals = {row["second"]: row["boxes"] for row in detections["timeline"]}
    timelines = {name: [] for name in ("baseline", "reciprocal", "reciprocal_mean")}
    accepted = {name: {} for name in timelines}
    for frame in value["timeline"]:
        boxes, second = frame["boxes"], frame["second"]
        confirmed, reciprocal = correspondences(boxes, proposals[second], minimum_iou)
        fused = [
            {
                **box,
                **{
                    key: (box[key] + proposals[second][reciprocal[i]][key]) / 2
                    for key in BOUNDS
                },
            }
            if i in reciprocal
            else box.copy()
            for i, box in enumerate(boxes)
        ]
        for name in timelines:
            pairs = confirmed if name == "baseline" else reciprocal
            accepted[name][second] = {boxes[i]["track_id"] for i in pairs}
            timelines[name].append(
                {**frame, "boxes": fused if name == "reciprocal_mean" else boxes}
            )
    return timelines, accepted


def evaluate(args):
    frozen = json.loads(args.consensus_protocol.read_text())
    for path, expected in frozen["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Changed frozen consensus input: {path}")
    protocol, rules, value, detections, clip = load_inputs(args)
    changed, conflicts, _ = replay(
        value,
        args.propagation.parent,
        clip,
        rules,
        range(1, len(protocol["seeded_cows"]) + 1),
    )
    timelines, accepted = prepare_conditions(changed, detections, frozen["minimum_iou"])
    records, _ = annotations(args)
    quality = probability_gate(rules["base"]["minimum_p10_probability"])
    conditions = {}
    for name, timeline in timelines.items():

        def allowed(frame, box, confirmations=accepted[name]):
            return (
                quality(frame, box)
                and box.track_id + 1 not in conflicts[frame["second"]]
                and box.track_id in confirmations[frame["second"]]
            )

        conditions[name] = {
            str(window[0]): score(
                {**changed, "timeline": timeline},
                records,
                clip,
                {**protocol, "score_seconds": window},
                value["provenance"]["seed_prompts"],
                name_allowed=allowed,
            )
            for window in protocol["comparison_windows"]
        }
    baseline = json.loads(args.baseline_report.read_text())["conditions"]
    if any(
        result != baseline[window]["frozen_pipeline"]["metrics"]
        for window, result in conditions["baseline"].items()
    ):
        raise ValueError(
            "Consensus replay must reproduce every original baseline metric"
        )
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.consensus_protocol),
        "conditions": conditions,
        "baseline_exactly_reproduced": True,
        "selection": "No threshold search or automatic promotion",
    }
    write_json(args.output, report)
    print(json.dumps(conditions))


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
        "baseline-report",
        "consensus-protocol",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    evaluate(parser.parse_args())
