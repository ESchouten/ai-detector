"""Compare frozen mask cleanup and confidence rules on cached Cutie calibration."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_sam_tracking import score
from video_assessment import annotations


def largest_components(mask):
    """Keep one 8-connected component per original object, never renumber slots."""
    cleaned = np.zeros_like(mask)
    statistics = []
    for object_id in np.unique(mask):
        if object_id == 0:
            continue
        count, labels, stats, _ = cv2.connectedComponentsWithStatsWithAlgorithm(
            (mask == object_id).astype(np.uint8), 8, cv2.CV_32S, cv2.CCL_WU
        )
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        cleaned[labels == component] = object_id
        statistics.append(
            {
                "track_id": int(object_id) - 1,
                "component_count": count - 1,
                "original_area": int(stats[1:, cv2.CC_STAT_AREA].sum()),
                "retained_area": int(stats[component, cv2.CC_STAT_AREA]),
            }
        )
    return cleaned, statistics


def verified_mask(directory, frame, shape, seeded_count):
    path = directory / "masks" / f"{frame['second']}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Cached mask content does not match its frame hash")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if (
        mask is None
        or mask.dtype != np.uint8
        or mask.shape != shape
        or not set(np.unique(mask)).issubset(range(seeded_count + 1))
    ):
        raise ValueError("Indexed mask shape, type or original object IDs changed")
    if boxes_from_mask(mask) != frame["boxes"]:
        raise ValueError("Raw cached boxes differ from the original indexed mask")
    tracks = [box["track_id"] for box in frame["boxes"]]
    if [item["track_id"] for item in frame["objects"]] != tracks:
        raise ValueError("Mask confidence metadata does not match original slots")
    for item in frame["objects"]:
        if item["area"] != int((mask == item["track_id"] + 1).sum()):
            raise ValueError("Mask area differs from cached probability metadata")
        for key in ("mean_probability", "p10_probability"):
            probability = item[key]
            if not np.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("Invalid assigned-object probability")
    return mask


def box_variants(value, directory, clip, protocol):
    start, end = protocol["score_seconds"]
    changed, statistics = [], []
    for frame in value["timeline"]:
        if not start <= frame["second"] <= end:
            changed.append(frame)
            continue
        mask = verified_mask(
            directory,
            frame,
            (clip["height"], clip["width"]),
            len(protocol["seeded_cows"]),
        )
        cleaned, objects = largest_components(mask)
        changed.append({**frame, "boxes": boxes_from_mask(cleaned)})
        statistics.append({"second": frame["second"], "objects": objects})
    return {
        "raw": value,
        "largest_8_connected_component": {**value, "timeline": changed},
    }, statistics


def probability_gate(threshold):
    def allowed(frame, box):
        return (
            next(
                item["p10_probability"]
                for item in frame["objects"]
                if item["track_id"] == box.track_id
            )
            >= threshold
        )

    return allowed


def measure(variants, records, clip, protocol):
    results = []
    for variant in protocol["quality_control"]["box_variants"]:
        value = variants[variant]
        for threshold in protocol["quality_control"]["thresholds"]:
            metrics = score(
                value,
                records,
                clip,
                protocol,
                value["provenance"]["seed_prompts"],
                name_allowed=probability_gate(threshold),
            )
            counts = metrics["naming_counts"]
            results.append(
                {
                    "box_variant": variant,
                    "minimum_p10_probability": threshold,
                    "unknown_false_naming_rate": counts["unknown_named"]
                    / counts["visible_unknown"],
                    "metrics": metrics,
                }
            )
    return results


def choose(results, minimum_coverage):
    qualified = [
        row
        for row in results
        if row["metrics"]["conservative_precision"] >= 0.99
        and row["unknown_false_naming_rate"] <= 0.01
    ]
    if not qualified:
        return {"selected": None, "meets_all_gates": False}
    selected = min(
        qualified,
        key=lambda row: (
            -row["metrics"]["known_coverage"],
            -row["metrics"]["conservative_precision"],
            row["box_variant"] != "raw",
            row["minimum_p10_probability"],
        ),
    )
    return {
        "selected": selected,
        "meets_all_gates": selected["metrics"]["known_coverage"] >= minimum_coverage,
    }


def load_inputs(args):
    value = json.loads(args.propagation.read_text())
    protocol = json.loads(args.protocol.read_text())
    clip = json.loads(args.sampled_manifest.read_text())
    if (
        not value["complete"]
        or value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or digest(args.sampled_manifest) != protocol["sampled_manifest_sha256"]
        or clip["contract"]["video_sha256"] != protocol["video_sha256"]
        or digest(args.source_pickle) != protocol["source_annotations_sha256"]
    ):
        raise ValueError("Calibration is incomplete or its frozen provenance changed")
    if protocol["score_seconds"] != [1230, 1529]:
        raise ValueError(
            "Operating point selection requires the frozen calibration window"
        )
    if [row["second"] for row in value["timeline"]] != list(
        range(protocol["last_processed_second"] + 1)
    ) or len(value["frame_seconds"]) != len(clip["rows"]):
        raise ValueError("Calibration must contain every frozen source timestamp")
    return value, protocol, clip


def replay_development(args, value, protocol, clip, records, selection):
    """Apply the calibration choice once; exposed development cannot select it."""
    selected = selection["selected"]
    if selected is None:
        return {"selected": None, "metrics": None}
    development = {**protocol, "score_seconds": [330, 629]}
    variants, _ = box_variants(value, args.propagation.parent, clip, development)
    metrics = score(
        variants[selected["box_variant"]],
        records,
        clip,
        development,
        value["provenance"]["seed_prompts"],
        name_allowed=probability_gate(selected["minimum_p10_probability"]),
    )
    return {
        "scope": "Exposed development replay of the calibration choice, without retuning; no reserved-test or deployment claim",
        "calibration_report_sha256": digest(args.output),
        "propagation_sha256": digest(args.propagation),
        "protocol_sha256": digest(args.protocol),
        "runner_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "score_seconds": development["score_seconds"],
        "selected": {
            "box_variant": selected["box_variant"],
            "minimum_p10_probability": selected["minimum_p10_probability"],
        },
        "calibration_met_all_gates": selection["meets_all_gates"],
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "protocol",
        "sampled-manifest",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--development-output", type=Path)
    args = parser.parse_args()
    value, protocol, clip = load_inputs(args)
    records, _ = annotations(args)
    variants, statistics = box_variants(value, args.propagation.parent, clip, protocol)
    results = measure(variants, records, clip, protocol)
    selection = choose(results, protocol["quality_control"]["minimum_useful_coverage"])
    report = {
        "scope": "Frozen calibration-only operating point selection; no deployment or reserved-test claim",
        "propagation_sha256": digest(args.propagation),
        "protocol_sha256": digest(args.protocol),
        "annotations_sha256": digest(args.annotations),
        "runner_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "opencv": cv2.__version__,
        "component_algorithm": "OpenCV SAUF/Wu,8-connected,row-major labels; largest area, first equal-area label",
        "conditions": results,
        "component_statistics": statistics,
        **selection,
    }
    write_json(args.output, report)
    if args.development_output:
        write_json(
            args.development_output,
            replay_development(args, value, protocol, clip, records, selection),
        )
    print(json.dumps(selection))


if __name__ == "__main__":
    main()
