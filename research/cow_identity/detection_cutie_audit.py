"""Replay frozen Cutie scores and inspect every named error without inference."""

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_errors import overlaps
from detection_sam_tracking import score
from video_assessment import annotations, pair_boxes, pixels_hash, read_frame, truth_at

from aidetector.domain.models import BoundingBox


def named_errors(value, records, protocol, video):
    rows = []
    seeds = value["provenance"]["seed_prompts"]
    for frame in value["timeline"]:
        if (
            not protocol["score_seconds"][0]
            <= frame["second"]
            <= protocol["score_seconds"][1]
        ):
            continue
        truth = truth_at(
            records,
            round(frame["second"] * video["source_fps"]) + 1,
            video["width"],
            video["height"],
        )
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        paired = pair_boxes(boxes, truth)
        for index, box in enumerate(boxes):
            cow = seeds[box.track_id]["cow"]
            actual = truth[paired[index]]["cow"] if index in paired else None
            if cow not in protocol["named_cows"] or actual == cow:
                continue
            values = overlaps(box, truth)
            rows.append(
                {
                    "second": frame["second"],
                    "seed": cow,
                    "assigned_cow": actual,
                    "box": [box.x1, box.y1, box.x2, box.y2],
                    "own_truth": next(row["box"] for row in truth if row["cow"] == cow),
                    "own_overlap": next(row for row in values if row["cow"] == cow),
                    "best_overlap": max(values, key=lambda row: row["iou"]),
                    "all_overlaps": values,
                }
            )
    return rows


def review_images(capture, errors, directory, fps):
    directory.mkdir(parents=True, exist_ok=True)
    panels, images = [], []
    for row in errors:
        frame_id, source = read_frame(capture, row["second"], fps)
        image = source.copy()
        for box, color in ((row["own_truth"], (0, 240, 0)), (row["box"], (0, 0, 255))):
            cv2.rectangle(image, tuple(box[:2]), tuple(box[2:]), color, 2)
        name = f"second-{row['second']:04d}-seed-{row['seed']}.jpg"
        if not cv2.imwrite(str(directory / name), image):
            raise ValueError("Could not save review image")
        images.append(
            {
                "second": row["second"],
                "seed": row["seed"],
                "publisher_frame": frame_id,
                "pixels_sha256": pixels_hash(source),
                "file": name,
                "sha256": digest(directory / name),
            }
        )
        panel = np.zeros((335, 400, 3), dtype=np.uint8)
        panel[35:] = cv2.resize(image, (400, 300))
        label = (
            f"{row['second']}s seed{row['seed']} IoU={row['own_overlap']['iou']:.3f}"
        )
        cv2.putText(
            panel, label, (5, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
        )
        panels.append(panel)
    for offset in range(0, len(panels), 16):
        page = np.zeros((335 * 4, 400 * 4, 3), dtype=np.uint8)
        for index, panel in enumerate(panels[offset : offset + 16]):
            y, x = divmod(index, 4)
            page[y * 335 : (y + 1) * 335, x * 400 : (x + 1) * 400] = panel
        if not cv2.imwrite(str(directory / f"contact-{offset // 16}.jpg"), page):
            raise ValueError("Could not save review contact sheet")
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "protocol",
        "retained-report",
        "video",
        "annotations",
        "source-pickle",
        "images",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.propagation.read_text())
    protocol = json.loads(args.protocol.read_text())
    retained = json.loads(args.retained_report.read_text())
    if (
        not value["complete"]
        or digest(args.protocol) != value["provenance"]["protocol_sha256"]
    ):
        parser.error("Propagation is incomplete or protocol provenance changed")
    if digest(args.video) != protocol["video_sha256"]:
        parser.error("Unexpected source video")
    records, _ = annotations(args)
    capture = cv2.VideoCapture(str(args.video))
    video = {
        "source_fps": capture.get(cv2.CAP_PROP_FPS),
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    metrics = score(
        value, records, video, protocol, value["provenance"]["seed_prompts"]
    )
    errors = named_errors(value, records, protocol, video)
    try:
        images = review_images(capture, errors, args.images, video["source_fps"])
    finally:
        capture.release()
    report = {
        "scope": "Independent frozen Cutie metric replay and every named-error geometry; no adjusted metrics or model tuning",
        "propagation_sha256": digest(args.propagation),
        "protocol_sha256": digest(args.protocol),
        "annotations_sha256": digest(args.annotations),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "metrics_exactly_equal_retained": metrics == retained["metrics"],
        "metrics": metrics,
        "errors_by_seed": dict(Counter(row["seed"] for row in errors)),
        "errors": errors,
        "review_images": images,
        "limitations": "Green shows the named cow's publisher box; red shows the propagated box. Raw predicted masks were not cached. Large boxes cannot distinguish mask leakage, disconnected fragments, and physical identity drift by themselves.",
    }
    write_json(args.output, report)
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("errors", "review_images", "metrics")
            }
        )
    )


if __name__ == "__main__":
    main()
