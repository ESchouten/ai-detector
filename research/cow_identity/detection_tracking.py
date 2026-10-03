"""Compare SDK trackers/sampling on development video at common scoring times."""

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import lap
import numpy as np
from benchmark import digest, write_json
from detection_assessment import PROTOCOL
from video_assessment import (
    VideoMetrics,
    annotations,
    detector_libraries,
    read_frame,
    truth_at,
)

from aidetector.domain.models import BoundingBox


def track(args, provenance):
    from ultralytics import YOLO

    model = YOLO(str(args.model))
    records, _ = annotations(args)
    capture = cv2.VideoCapture(str(args.video))
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    timeline = []
    started = time.perf_counter()
    try:
        for index in range(300 * args.rate):
            second = args.start + index / args.rate
            frame_id, image = read_frame(capture, second, source_fps)
            result = model.track(
                image,
                persist=True,
                classes=[0],
                device=args.device,
                tracker=args.tracker,
                imgsz=640,
                conf=args.tracking_confidence or args.confidence,
                quantize=16,
                verbose=False,
            )[0]
            if index % args.rate:
                continue
            boxes = result.boxes[result.boxes.conf >= args.confidence]
            ids = (
                [None] * len(boxes)
                if boxes.id is None
                else [int(value) for value in boxes.id.cpu().tolist()]
            )
            timeline.append(
                {
                    "second": int(second),
                    "truth": truth_at(
                        records, frame_id, image.shape[1], image.shape[0]
                    ),
                    "boxes": [
                        asdict(
                            BoundingBox(
                                *(int(value) for value in xyxy), "cow", score, track_id
                            )
                        )
                        for xyxy, score, track_id in zip(
                            boxes.xyxy.cpu().tolist(),
                            boxes.conf.cpu().tolist(),
                            ids,
                            strict=True,
                        )
                    ],
                }
            )
    finally:
        capture.release()
    return {
        "provenance": provenance,
        "timeline": timeline,
        "elapsed_seconds": time.perf_counter() - started,
        "inferred_frames": 300 * args.rate,
        "device": str(model.predictor.model.device),
        "fp16": model.predictor.model.fp16,
        "resolved_tracker_settings": vars(model.predictor.trackers[0].args),
        "native_feature_hook_active": hasattr(model.predictor, "_hook"),
    }


def summarize(value):
    metrics, associations = VideoMetrics(), Counter()
    for frame in value["timeline"]:
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        decisions = metrics.add(
            frame["second"], boxes, frame["truth"], [True] * len(boxes)
        )
        for row in decisions:
            if row["track"] is not None and row["truth"] is not None:
                associations[row["track"], row["truth"]] += 1
    tracks = sorted({track for track, _ in associations})
    cows = sorted({cow for _, cow in associations})
    matrix = np.array([[associations[track, cow] for cow in cows] for track in tracks])
    if matrix.size:
        _, assignments, _ = lap.lapjv(-matrix.astype(float), extend_cost=True)
        idtp = sum(
            int(matrix[row, col]) for row, col in enumerate(assignments) if col >= 0
        )
    else:
        idtp = 0
    counts = metrics.counts
    return {
        "counts": dict(counts),
        "precision": counts["matched_boxes"] / counts["detector_boxes"]
        if counts["detector_boxes"]
        else 0.0,
        "recall": counts["matched_boxes"] / counts["visible_annotations"],
        "global_identity_true_positives": idtp,
        "global_identity_f1": 2
        * idtp
        / (counts["visible_annotations"] + counts["detector_boxes"]),
        "note": "Global one-to-one track/cow assignment at IoU .5 on 1 fps scoring timestamps; not permanent cow recognition.",
    }


def main():
    from ultralytics.utils import ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "video", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--rate", type=int, choices=(1, 5), required=True)
    parser.add_argument("--start", type=int, choices=(330, 930, 1230), default=330)
    parser.add_argument("--tracker", required=True)
    parser.add_argument("--confidence", type=float, required=True)
    parser.add_argument("--tracking-confidence", type=float)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--cache", type=Path, default=Path(".cache/cow-detectors"))
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    if digest(args.video) != protocol["video_sha256"]:
        parser.error("Unexpected video")
    tracker_file = Path(args.tracker)
    if not tracker_file.exists():
        tracker_file = ROOT / "cfg/trackers" / args.tracker
    provenance = {
        "version": 1,
        "protocol_sha256": digest(args.protocol),
        "model": digest(args.model),
        "annotations": digest(args.annotations),
        "video": protocol["video_sha256"],
        "device": args.device,
        "library_versions": detector_libraries(),
        "tracker": args.tracker,
        "tracker_sha256": digest(tracker_file),
        "inference_fps": args.rate,
        "scoring_fps": 1,
        "start": args.start,
        "seconds": 300,
        "confidence": args.confidence,
        "imgsz": 640,
        "sdk_tracker_frame_rate": 30,
    }
    if args.tracking_confidence is not None:
        provenance["tracking_confidence"] = args.tracking_confidence
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cache = args.cache / f"tracking-{key}.json"
    cached = cache.exists()
    value = json.loads(cache.read_text()) if cached else track(args, provenance)
    if not cached:
        write_json(cache, value)
    result = {**value, "cache_reused": cached, "metrics": summarize(value)}
    write_json(args.output, result)
    print(json.dumps({key: row for key, row in result.items() if key != "timeline"}))


if __name__ == "__main__":
    main()
