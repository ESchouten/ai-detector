"""Separate initialization, raw detector and quarantine effects on exposed video."""

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_corroboration import maximum_iou
from detection_cutie import boxes_from_mask
from detection_cutie_audit import review_images
from detection_cutie_variants import largest_components, probability_gate, verified_mask
from detection_errors import overlaps
from detection_sam_tracking import score
from video_assessment import annotations, pair_boxes, pixels_hash, read_frame, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
PROTOCOL = ROOT / "detection_actual_audit_protocol.json"
FILES = {
    "actual": Path(".cache/cow-cutie/actual-seed-2fps/propagation.json"),
    "original": Path(".cache/cow-cutie/calibration-2fps/propagation.json"),
    "raw": Path(".cache/cow-cutie/actual-seed-corroborator.json"),
    "actual_report": ROOT
    / "results/2026-10-03/detection/cutie-actual-seed-pipeline.json",
    "original_quarantine": ROOT
    / "results/2026-10-03/detection/cutie-quarantine-v2.json",
    "tracked_report": ROOT
    / "results/2026-10-03/detection/cutie-detector-corroboration.json",
    "source_protocol": ROOT / "detection_actual_seed_protocol.json",
    "clip": Path(".cache/cow-cutie/calibration-clip/sampled.json"),
}


def freeze():
    if PROTOCOL.exists():
        raise ValueError("Preserve the original audit freeze")
    write_json(
        PROTOCOL,
        {
            "scope": "Fixed causal controls on exposed development; no new threshold selection",
            "files": {
                key: {"path": str(path), "sha256": digest(path)}
                for key, path in FILES.items()
            },
            "conditions": [
                "actual_no_quarantine",
                "actual_quarantine",
                "original_quarantine_raw",
            ],
            "policy": "Original LCC geometry, p10>=.7, raw same-frame YOLO IoU>=.5. Only listed quarantine/init differences; original decisions retained as controls. Names and strict truth matching unchanged.",
            "windows": [[330, 629], [930, 1229], [1230, 1529]],
            "runner_sha256": digest(Path(__file__)),
        },
    )


def lcc_timeline(value, directory, clip):
    cache = directory / "largest-component-boxes.json"
    contract = {
        "propagation_sha256": digest(directory / "propagation.json"),
        "component_helper_sha256": digest(ROOT / "detection_cutie_variants.py"),
        "opencv": cv2.__version__,
    }
    if cache.exists():
        retained = json.loads(cache.read_text())
        if retained["contract"] == contract:
            return {**value, "timeline": retained["timeline"]}
    rows = []
    for frame in value["timeline"]:
        mask = verified_mask(directory, frame, (clip["height"], clip["width"]), 8)
        cleaned, _ = largest_components(mask)
        rows.append({**frame, "boxes": boxes_from_mask(cleaned)})
    write_json(cache, {"contract": contract, "timeline": rows})
    return {**value, "timeline": rows}


def review_absent(capture, errors, directory, fps):
    """A named cow absent from truth has no green own-cow rectangle to draw."""
    images = []
    for row in errors:
        frame_id, source = read_frame(capture, row["second"], fps)
        image = source.copy()
        box = row["box"]
        cv2.rectangle(image, tuple(box[:2]), tuple(box[2:]), (0, 0, 255), 2)
        cv2.putText(
            image,
            f"Named cow {row['seed']} is not annotated",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )
        path = directory / f"absent-second-{row['second']:04d}-seed-{row['seed']}.jpg"
        if not cv2.imwrite(str(path), image):
            raise ValueError("Could not save absent-cow review image")
        images.append(
            {
                "second": row["second"],
                "seed": row["seed"],
                "publisher_frame": frame_id,
                "pixels_sha256": pixels_hash(source),
                "file": path.name,
                "sha256": digest(path),
            }
        )
    return images


def render(args, errors, clip):
    capture = cv2.VideoCapture(str(args.video))
    try:
        images = review_images(
            capture,
            [row for row in errors if row["own_truth"] is not None],
            args.images,
            clip["source_fps"],
        )
        images.extend(
            review_absent(
                capture,
                [row for row in errors if row["own_truth"] is None],
                args.images,
                clip["source_fps"],
            )
        )
        return images
    finally:
        capture.release()


def gate(detections, conflicts):
    quality = probability_gate(0.7)

    def allowed(frame, box):
        return (
            quality(frame, box)
            and box.track_id + 1 not in conflicts.get(str(frame["second"]), [])
            and maximum_iou(vars(box), detections[frame["second"]]) >= 0.5
        )

    return allowed


def error_rows(value, records, clip, protocol, allowed, windows):
    result = []
    seeds = value["provenance"]["seed_prompts"]
    for frame in value["timeline"]:
        if not any(start <= frame["second"] <= stop for start, stop in windows):
            continue
        truth = truth_at(
            records,
            frame["second"] * clip["source_fps"] + 1,
            clip["width"],
            clip["height"],
        )
        boxes = [BoundingBox(**box) for box in frame["boxes"]]
        paired = pair_boxes(boxes, truth)
        for index, box in enumerate(boxes):
            cow = seeds[box.track_id]["cow"]
            actual = truth[paired[index]]["cow"] if index in paired else None
            if (
                cow not in protocol["named_cows"]
                or not allowed(frame, box)
                or actual == cow
            ):
                continue
            values = overlaps(box, truth)
            own = next((row for row in truth if row["cow"] == cow), None)
            result.append(
                {
                    "second": frame["second"],
                    "seed": cow,
                    "assigned_cow": actual,
                    "box": [box.x1, box.y1, box.x2, box.y2],
                    "own_truth": own["box"] if own else None,
                    "own_overlap": next(
                        (row for row in values if row["cow"] == cow), None
                    ),
                    "best_overlap": max(values, key=lambda row: row["iou"]),
                    "all_overlaps": values,
                }
            )
    return result


def run(args):
    frozen = json.loads(PROTOCOL.read_text())
    if digest(Path(__file__)) != frozen["runner_sha256"]:
        raise ValueError("Audit implementation changed after freeze")
    data = {}
    for key, source in frozen["files"].items():
        path = Path(source["path"])
        if digest(path) != source["sha256"]:
            raise ValueError(f"Changed frozen audit input: {path}")
        data[key] = json.loads(path.read_text())
    records, _ = annotations(args)
    clip, protocol = data["clip"], data["source_protocol"]
    detections = {frame["second"]: frame["boxes"] for frame in data["raw"]["timeline"]}
    values = {
        key: lcc_timeline(data[key], FILES[key].parent, clip)
        for key in ("actual", "original")
    }
    conditions = (
        ("actual_no_quarantine", "actual", {}),
        (
            "actual_quarantine",
            "actual",
            data["actual_report"]["conflicted_ids_by_second"],
        ),
        (
            "original_quarantine_raw",
            "original",
            data["original_quarantine"]["conflicted_ids_by_second"],
        ),
    )
    metrics, errors = {}, {}
    for name, key, conflicts in conditions:
        allowed = gate(detections, conflicts)
        metrics[name] = {
            str(window[0]): score(
                values[key],
                records,
                clip,
                {**protocol, "score_seconds": window},
                values[key]["provenance"]["seed_prompts"],
                name_allowed=allowed,
            )
            for window in frozen["windows"]
        }
        errors[name] = error_rows(
            values[key], records, clip, protocol, allowed, frozen["windows"]
        )
    if digest(args.video) != protocol["video_sha256"]:
        raise ValueError("Unexpected source video")
    report = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "conditions": metrics,
        "errors": errors,
        "review_images_complete": False,
        "actual_metrics_exactly_reproduced": all(
            metrics["actual_quarantine"][start] == row["frozen_pipeline"]["metrics"]
            for start, row in data["actual_report"]["conditions"].items()
        ),
        "actual_errors_by_seed": dict(
            Counter(row["seed"] for row in errors["actual_quarantine"])
        ),
    }
    write_json(args.output, report)
    print(json.dumps({"conditions": metrics}), flush=True)
    images = render(args, errors["actual_quarantine"], clip)
    write_json(
        args.output, {**report, "review_images": images, "review_images_complete": True}
    )
    print(
        json.dumps(
            {
                "conditions": metrics,
                "errors_by_seed": dict(
                    Counter(row["seed"] for row in errors["actual_quarantine"])
                ),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    for name in ("video", "annotations", "source-pickle", "images", "output"):
        parser.add_argument(f"--{name}", type=Path)
    arguments = parser.parse_args()
    if arguments.action == "freeze":
        freeze()
    else:
        run(arguments)
