"""Test a cached, independent detector geometry veto of original Cutie names."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components, probability_gate, verified_mask
from detection_sam_tracking import score
from video_assessment import annotations, pixels_hash


def maximum_iou(box, candidates):
    overlaps = [0.0]
    for other in candidates:
        intersection = max(
            0, min(box["x2"], other["x2"]) - max(box["x1"], other["x1"])
        ) * max(0, min(box["y2"], other["y2"]) - max(box["y1"], other["y1"]))
        area = (box["x2"] - box["x1"]) * (box["y2"] - box["y1"])
        other_area = (other["x2"] - other["x1"]) * (other["y2"] - other["y1"])
        overlaps.append(intersection / (area + other_area - intersection))
    return max(overlaps)


def verify_predictions(source, video, protocol, clip, capture):
    path = Path(source["tracking"])
    feature_path = Path(source["features"])
    if (
        digest(path) != source["tracking_sha256"]
        or digest(feature_path) != source["features_sha256"]
    ):
        raise ValueError("Changed independent detector cache")
    value, features = json.loads(path.read_text()), json.loads(feature_path.read_text())
    provenance = value["provenance"]
    if (
        provenance["model"] != protocol["model_sha256"]
        or provenance["video"] != video
        or provenance["confidence"] != 0.4
        or provenance["inference_fps"] != 1
        or features["contract"]["tracking_sha256"] != digest(path)
        or [row["second"] for row in value["timeline"]]
        != list(range(source["start"], source["stop"] + 1))
    ):
        raise ValueError(
            "Detector source/model/cadence differs from the frozen comparison"
        )
    evidence = {row["second"]: row for row in features["frames"]}
    source_rows = {
        row["second"]: (index, row) for index, row in enumerate(clip["rows"])
    }
    capture.set(cv2.CAP_PROP_POS_FRAMES, source_rows[source["start"]][0])
    frame_digest = hashlib.sha256()
    for row in value["timeline"]:
        index, expected = source_rows[row["second"]]
        while capture.get(cv2.CAP_PROP_POS_FRAMES) < index:
            if not capture.grab():
                raise ValueError("Cached source clip ended before the detector frame")
        ok, image = capture.read()
        if not ok or pixels_hash(image) != expected["pixels_sha256"]:
            raise ValueError("Cached source-frame pixels changed")
        frame_digest.update(expected["pixels_sha256"].encode())
        candidates = [
            features["rows"][index] for index in evidence[row["second"]]["rows"]
        ]
        for box, candidate in zip(row["boxes"], candidates, strict=True):
            bounds = [box[key] for key in ("x1", "y1", "x2", "y2")]
            x1, y1, x2, y2 = bounds
            if (
                candidate["box"] != bounds
                or candidate["frame"] != expected["publisher_frame"]
                or pixels_hash(image[y1:y2, x1:x2]) != candidate["pixels_sha256"]
            ):
                raise ValueError(
                    "Detector proposal no longer matches its verified source crop"
                )
    return value["timeline"], frame_digest.hexdigest()


def prepare(args, protocol, value, clip):
    detections, audits = {}, []
    capture = cv2.VideoCapture(str(args.sampled_manifest.with_name("sampled.avi")))
    try:
        for source in protocol["sources"]:
            rows, proof = verify_predictions(
                source, clip["contract"]["video_sha256"], protocol, clip, capture
            )
            detections.update({row["second"]: row["boxes"] for row in rows})
            audits.append(
                {
                    "start": source["start"],
                    "frames": len(rows),
                    "source_frame_hashes_sha256": proof,
                }
            )
    finally:
        capture.release()
    changed, overlap = [], {}
    for frame in value["timeline"]:
        second = frame["second"]
        if second not in detections:
            changed.append(frame)
            continue
        mask = verified_mask(
            args.propagation.parent, frame, (clip["height"], clip["width"]), 8
        )
        cleaned, _ = largest_components(mask)
        boxes = boxes_from_mask(cleaned)
        overlap[second] = {
            box["track_id"]: maximum_iou(box, detections[second]) for box in boxes
        }
        changed.append({**frame, "boxes": boxes})
    return {**value, "timeline": changed}, overlap, detections, audits


def measure(
    value,
    records,
    clip,
    source_protocol,
    protocol,
    quarantine,
    overlap,
    window,
    threshold,
):
    quality = probability_gate(protocol["minimum_p10_probability"])
    rejected, base_names = [], []

    def allowed(frame, box):
        second = frame["second"]
        original = (
            quality(frame, box)
            and box.track_id + 1
            not in quarantine["conflicted_ids_by_second"][str(second)]
        )
        if original:
            base_names.append((second, box.track_id))
        corroborated = threshold is None or overlap[second][box.track_id] >= threshold
        if original and not corroborated:
            rejected.append((second, box.track_id))
        return original and corroborated

    metrics = score(
        value,
        records,
        clip,
        {**source_protocol, "score_seconds": window},
        value["provenance"]["seed_prompts"],
        name_allowed=allowed,
    )
    return {
        "minimum_iou": threshold,
        "metrics": metrics,
        "base_named_boxes": len(base_names),
        "names_without_required_corroboration": len(rejected),
        "unknown_false_naming_rate": metrics["naming_counts"]["unknown_named"]
        / metrics["naming_counts"]["visible_unknown"],
    }


def choose(conditions):
    eligible = [
        row
        for row in conditions
        if row["metrics"]["conservative_precision"] >= 0.99
        and row["unknown_false_naming_rate"] <= 0.01
    ]
    return min(
        eligible,
        key=lambda row: (
            -row["metrics"]["known_coverage"],
            -row["metrics"]["conservative_precision"],
            row["minimum_iou"] or 0,
        ),
        default=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "source-protocol",
        "sampled-manifest",
        "quarantine",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    path = Path(__file__).with_name("detection_corroboration_protocol.json")
    protocol = json.loads(path.read_text())
    for name, key in (
        ("propagation", "propagation_sha256"),
        ("source_protocol", "source_protocol_sha256"),
        ("quarantine", "quarantine_report_sha256"),
    ):
        if digest(getattr(args, name)) != protocol[key]:
            parser.error(f"Changed frozen {name}")
    value, source, clip, quarantine = [
        json.loads(getattr(args, name).read_text())
        for name in ("propagation", "source_protocol", "sampled_manifest", "quarantine")
    ]
    if (
        not value["complete"]
        or digest(args.sampled_manifest) != source["sampled_manifest_sha256"]
        or digest(args.sampled_manifest.with_name("sampled.avi")) != clip["clip_sha256"]
    ):
        parser.error("Original source inference/pixels are incomplete or changed")
    value, overlap, detections, audits = prepare(args, protocol, value, clip)
    records, metadata = annotations(args)
    if metadata["source_sha256"] != source["source_annotations_sha256"]:
        parser.error("Changed publisher annotations")

    def conditions(window):
        return [
            measure(
                value,
                records,
                clip,
                source,
                protocol,
                quarantine,
                overlap,
                window,
                threshold,
            )
            for threshold in (None, *protocol["thresholds"])
        ]

    calibration = conditions(protocol["selection_window"])
    selected = choose(calibration)
    development = {
        str(window[0]): conditions(window) for window in protocol["development_windows"]
    }
    report = {
        "protocol": protocol,
        "protocol_sha256": digest(path),
        "runner_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "source_pixel_audits": audits,
        "calibration": calibration,
        "selected": selected,
        "meets_calibration_gates": bool(
            selected and selected["metrics"]["known_coverage"] >= 0.6
        ),
        "development_conditions": development,
        "selected_development_replays": {
            start: next(
                row for row in rows if row["minimum_iou"] == selected["minimum_iou"]
            )
            for start, rows in development.items()
        }
        if selected
        else {},
        "detector_counts_by_second": {
            second: len(rows) for second, rows in detections.items()
        },
        "maximum_iou_by_second_and_original_slot": overlap,
    }
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "selected": selected,
                "development_replays": report["selected_development_replays"],
            }
        )
    )


if __name__ == "__main__":
    main()
