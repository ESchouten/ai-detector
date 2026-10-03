"""Test a fixed visible-mask box margin while retaining all strict identity errors."""

import argparse
import json
import math
from pathlib import Path

from benchmark import digest, write_json
from cutie_appearance import load_inputs, predicted_timeline
from detection_cutie_variants import probability_gate
from detection_sam_tracking import score
from video_assessment import annotations


def padded_box(box, scale, width, height):
    """A small symmetric margin may include extremities missed by the mask."""
    if scale == 1:
        return box.copy()
    dx = (box["x2"] - box["x1"]) * (scale - 1) / 2
    dy = (box["y2"] - box["y1"]) * (scale - 1) / 2
    return {
        **box,
        "x1": max(0, math.floor(box["x1"] - dx)),
        "y1": max(0, math.floor(box["y1"] - dy)),
        "x2": min(width, math.ceil(box["x2"] + dx)),
        "y2": min(height, math.ceil(box["y2"] + dy)),
    }


def evaluate(args):
    protocol = json.loads(args.geometry_protocol.read_text())
    quarantine = json.loads(args.quarantine.read_text())
    for path, key in (
        (args.protocol, "appearance_protocol_sha256"),
        (args.quarantine, "quarantine_sha256"),
        (Path(__file__), "runner_sha256"),
    ):
        if digest(path) != protocol[key]:
            raise ValueError("Frozen geometric control inputs changed")
    _, tracking, propagation, clip, features, _, _, _ = load_inputs(args)
    value = predicted_timeline(propagation, features)
    if quarantine["propagation_sha256"] != digest(args.propagation):
        raise ValueError("Quarantine belongs to different source masks")
    records, _ = annotations(args)
    quality = probability_gate(protocol["minimum_p10_probability"])

    def allowed(frame, box):
        conflicts = quarantine["conflicted_ids_by_second"][str(frame["second"])]
        return quality(frame, box) and box.track_id + 1 not in conflicts

    def measure(scale, window):
        changed = {
            **value,
            "timeline": [
                {
                    **frame,
                    "boxes": [
                        padded_box(box, scale, clip["width"], clip["height"])
                        for box in frame["boxes"]
                    ],
                }
                for frame in value["timeline"]
            ],
        }
        metrics = score(
            changed,
            records,
            clip,
            {**tracking, "score_seconds": window},
            value["provenance"]["seed_prompts"],
            name_allowed=allowed,
        )
        counts = metrics["naming_counts"]
        return {
            "box_scale": scale,
            "metrics": metrics,
            "unknown_false_naming_rate": counts["unknown_named"]
            / counts["visible_unknown"],
        }

    results = [
        measure(scale, protocol["selection_window"]) for scale in protocol["box_scales"]
    ]
    qualified = [
        row
        for row in results
        if row["metrics"]["conservative_precision"] >= 0.99
        and row["unknown_false_naming_rate"] <= 0.01
    ]
    selected = min(
        qualified,
        key=lambda row: (
            -row["metrics"]["known_coverage"],
            -row["metrics"]["conservative_precision"],
            row["box_scale"],
        ),
        default=None,
    )
    replays = (
        {}
        if selected is None
        else {
            f"{start}-{end}": measure(selected["box_scale"], [start, end])
            for start, end in protocol["development_windows"]
        }
    )
    result = {
        "scope": "Exploratory mask-to-box correction on exposed footage, all original strict errors retained; manually initialized tracks, no held-out or runtime claim",
        "protocol_sha256": digest(args.geometry_protocol),
        "runner_sha256": digest(Path(__file__)),
        "conditions": results,
        "selected": selected,
        "development_replays": replays,
    }
    write_json(args.output, result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "geometry-protocol",
        "quarantine",
        "protocol",
        "tracking-protocol",
        "propagation",
        "sampled-manifest",
        "features",
        "gallery",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    evaluate(parser.parse_args())


if __name__ == "__main__":
    main()
