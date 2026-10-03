"""Strict development scoring and separate-engine parity for the joint runner."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_box_consensus import correspondences
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from detection_reserved_score import (
    acceptance,
    pooled_naming,
    runtime_summary,
    validate_timeline,
)
from detection_sam_tracking import score
from video_assessment import annotations

ROOT = Path(__file__).parent
BOUNDS = ("x1", "y1", "x2", "y2")
WINDOWS = [[330, 629], [930, 1229], [1230, 1529]]
THRESHOLDS = {
    "minimum_conservative_precision": 0.99,
    "minimum_known_coverage": 0.60,
    "maximum_unknown_false_naming_rate": 0.01,
}


def geometry(rows):
    return [tuple(box[key] for key in BOUNDS) for box in rows]


def checked_inputs(args):
    protocol = json.loads(args.protocol.read_text())
    value = json.loads(args.streaming.read_text())
    clip = json.loads((Path(protocol["inputs"]["clip"]) / "sampled.json").read_text())
    if (
        protocol["comparison_windows"] != WINDOWS
        or protocol["last_processed_second"] != 1529
    ):
        raise ValueError(
            "This assessment is restricted to the exposed development panels"
        )
    for path, expected in protocol["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen joint input changed: {path}")
    if (
        value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or value["provenance"]["libraries"] != protocol["libraries"]
        or [row["cow"] for row in value["provenance"]["seed_prompts"]]
        != protocol["seeded_cows"]
        or clip["contract"]["video_sha256"] != protocol["video_sha256"]
    ):
        raise ValueError("Joint inference provenance differs from the frozen method")
    validate_timeline(value, protocol, clip)
    selected = json.loads(
        (ROOT / "detection_recovery_consensus_protocol.json").read_text()
    )
    for path, expected in selected["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Selected separate-engine reference changed: {path}")
    for path in (args.annotations, args.source_pickle):
        if digest(path) != selected["files"][str(path)]:
            raise ValueError(
                "Development annotations differ from the selected reference"
            )
    return protocol, value, clip


def reference_parity(value, directory):
    reference_path = Path(".cache/cow-cutie/actual-seed-2fps/propagation.json")
    raw_path = Path(".cache/cow-cutie/actual-seed-corroborator.json")
    recovery_path = ROOT / "results/2026-10-03/detection/cutie-quarantine-recovery.json"
    original = json.loads(reference_path.read_text())
    detections = {
        row["second"]: row for row in json.loads(raw_path.read_text())["timeline"]
    }
    conflicts = json.loads(recovery_path.read_text())["conflicted_ids_by_second"]
    totals = {
        "different_mask_frames": 0,
        "different_mask_pixels": 0,
        "different_detector_geometry_frames": 0,
        "different_decision_frames": 0,
        "different_conflict_frames": 0,
        "different_lcc_geometry_frames": 0,
    }
    examples = []
    for frame, reference in zip(value["timeline"], original["timeline"], strict=True):
        second = frame["second"]
        if second != reference["second"]:
            raise ValueError("Separate and joint references have different times")
        masks = []
        for folder, row in ((directory, frame), (reference_path.parent, reference)):
            path = folder / "masks" / f"{second}.png"
            if digest(path) != row["mask_sha256"]:
                raise ValueError("Cached indexed mask changed")
            masks.append(cv2.imread(str(path), cv2.IMREAD_UNCHANGED))
        if masks[0].shape != masks[1].shape:
            raise ValueError("Joint and separate source mask shapes differ")
        changed = int(np.count_nonzero(masks[0] != masks[1]))
        totals["different_mask_frames"] += changed > 0
        totals["different_mask_pixels"] += changed
        cleaned, _ = largest_components(masks[0])
        derived = boxes_from_mask(cleaned)
        if [(b["track_id"], *(b[k] for k in BOUNDS)) for b in derived] != [
            (b["track_id"], *(b[k] for k in BOUNDS)) for b in frame["boxes"]
        ]:
            raise ValueError(
                "Recorded joint geometry differs from its own indexed mask"
            )
        old_cleaned, _ = largest_components(masks[1])
        old_boxes = boxes_from_mask(old_cleaned)
        proposals = detections[second]["boxes"]
        different_detector = geometry(proposals) != geometry(
            frame["raw_detector_boxes"]
        )
        totals["different_detector_geometry_frames"] += different_detector
        totals["different_lcc_geometry_frames"] += geometry(old_boxes) != geometry(
            frame["boxes"]
        )
        _, reciprocal = correspondences(old_boxes, proposals, 0.5)
        p10 = {row["track_id"]: row["p10_probability"] for row in reference["objects"]}
        blocked = conflicts[str(second)]
        names = {
            old_boxes[i]["track_id"]
            for i in reciprocal
            if old_boxes[i]["track_id"] < 6
            and old_boxes[i]["track_id"] + 1 not in blocked
            and p10[old_boxes[i]["track_id"]] >= 0.7
        }
        different_names = names != set(frame["named_track_ids"])
        different_conflicts = blocked != frame["conflicted_ids"]
        totals["different_decision_frames"] += different_names
        totals["different_conflict_frames"] += different_conflicts
        if len(examples) < 20 and (
            changed or different_detector or different_names or different_conflicts
        ):
            examples.append(
                {
                    "second": second,
                    "changed_pixels": changed,
                    "detector_geometry_changed": different_detector,
                    "names_changed": different_names,
                    "conflicts_changed": different_conflicts,
                }
            )
    return {
        **totals,
        "first_difference_examples": examples,
        "reference_sha256": {
            str(p): digest(p) for p in (reference_path, raw_path, recovery_path)
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "streaming", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    protocol, value, clip = checked_inputs(args)
    parity = reference_parity(value, args.streaming.parent)
    records, _ = annotations(args)
    windows = {
        str(window[0]): score(
            value,
            records,
            clip,
            {**protocol, "score_seconds": window},
            value["provenance"]["seed_prompts"],
            name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
        )
        for window in WINDOWS
    }
    baseline_path = ROOT / "results/2026-10-03/detection/cutie-recovery-consensus.json"
    baseline = json.loads(baseline_path.read_text())["conditions"][
        "fixed_reciprocal_conjunction"
    ]
    report = {
        "scope": "Joint app-runtime exposed-development verification. No reserved frames or blind-evaluation claim.",
        "protocol_sha256": digest(args.protocol),
        "streaming_sha256": digest(args.streaming),
        "conditions": windows,
        "pooled": pooled_naming(windows),
        "acceptance": {
            name: acceptance(row, THRESHOLDS) for name, row in windows.items()
        },
        "thresholds": THRESHOLDS,
        "separate_engine_metrics_equal": windows == baseline,
        "separate_engine_report_sha256": digest(baseline_path),
        "parity": parity,
        "runtime": runtime_summary(value, protocol["processing_fps"]),
        "scorer_sha256": {
            str(path): digest(path)
            for path in (
                Path(__file__),
                ROOT / "detection_reserved_score.py",
                ROOT / "detection_sam_tracking.py",
            )
        },
        "limitations": "Six manually named initial animals in one exposed recording; no automatic new arrivals, reconnect identities or proof of cross-day recognition.",
    }
    write_json(args.output, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "acceptance",
                    "pooled",
                    "separate_engine_metrics_equal",
                    "parity",
                    "runtime",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
