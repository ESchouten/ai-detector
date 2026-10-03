"""Measure whether actual first-frame proposals could initialize named tracking."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
from benchmark import digest, write_json
from video_assessment import (
    annotations,
    detector_libraries,
    pair_boxes,
    pixels_hash,
    read_frame,
    truth_at,
)

from aidetector.domain.models import BoundingBox


def predict(image, args, protocol):
    provenance = {
        "model_sha256": digest(args.model),
        "pixels_sha256": pixels_hash(image),
        "settings": protocol["settings"],
        "libraries": detector_libraries(),
    }
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    path = args.cache / f"proposals-{key}.json"
    if path.exists():
        return json.loads(path.read_text()), True
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(2)
    started = time.perf_counter()
    model = YOLO(str(args.model))
    result = model.predict(image, verbose=False, **protocol["settings"])[0]
    value = {
        "provenance": provenance,
        "boxes": result.boxes.xyxy.cpu().tolist(),
        "confidence": result.boxes.conf.cpu().tolist(),
        "elapsed_seconds": time.perf_counter() - started,
        "actual_device": str(model.predictor.model.device),
        "actual_fp16": model.predictor.model.fp16,
    }
    write_json(path, value)
    return value, False


def seed_metrics(boxes, truth, named_cows):
    matched = pair_boxes(boxes, truth)
    found = {truth[index]["cow"] for index in matched.values()}
    named = {row["cow"] for row in truth} & set(named_cows)
    return {
        "proposal_count": len(boxes),
        "matched_proposals": len(matched),
        "false_proposals": len(boxes) - len(matched),
        "missed_visible_cows": len(truth) - len(matched),
        "seed_recall": len(matched) / len(truth),
        "seed_precision": len(matched) / len(boxes) if boxes else 0,
        "correctly_seedable_known_ids": sorted(found & named),
        "missing_known_ids": sorted(named - found),
        "visible_known_coverage_ceiling": len(found & named) / len(named),
        "matched_proposal_to_cow": {
            str(index): truth[target]["cow"] for index, target in matched.items()
        },
    }


def draw(image, rows, labels, color):
    output = image.copy()
    for bounds, label in zip(rows, labels, strict=True):
        x1, y1, x2, y2 = map(int, bounds)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            output,
            label,
            (x1, max(16, y1)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "video", "annotations", "source-pickle", "cache", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    protocol_path = Path(__file__).with_name("detection_initialization_protocol.json")
    protocol = json.loads(protocol_path.read_text())
    for name, field in (
        ("model", "model_sha256"),
        ("video", "video_sha256"),
        ("source_pickle", "source_annotations_sha256"),
    ):
        if digest(getattr(args, name)) != protocol[field]:
            parser.error(f"Unexpected source {name}")
    capture = cv2.VideoCapture(str(args.video))
    try:
        frame, image = read_frame(capture, 0, capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    proposals, reused = predict(image, args, protocol)
    # Truth is deliberately loaded only after actual proposals have been cached.
    records, _ = annotations(args)
    truth = truth_at(records, frame, image.shape[1], image.shape[0])
    metrics = seed_metrics(
        [BoundingBox(*bounds) for bounds in proposals["boxes"]],
        truth,
        protocol["named_cows"],
    )
    predicted = draw(
        image,
        proposals["boxes"],
        [f"P{i}: {score:.2f}" for i, score in enumerate(proposals["confidence"])],
        (0, 150, 255),
    )
    annotated = draw(
        image,
        [row["box"] for row in truth],
        [f"Cow {row['cow']}" for row in truth],
        (0, 255, 0),
    )
    preview = args.cache / "first-frame-proposals-vs-truth.jpg"
    if not cv2.imwrite(str(preview), cv2.hconcat([predicted, annotated])):
        raise ValueError("Could not write source-proposal contact sheet")
    report = {
        "protocol": protocol,
        "protocol_sha256": digest(protocol_path),
        "runner_sha256": digest(Path(__file__)),
        "annotations_sha256": digest(args.annotations),
        "cache_reused": reused,
        "inference": proposals,
        "truth": truth,
        "metrics": metrics,
        "preview_sha256": digest(preview),
    }
    write_json(args.output, report)
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
