"""Author-detector localization on the exact frozen adult-cow oracle panels."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from annotation_audit import annotated_panel
from benchmark import digest, write_json
from ethz_oracle import source_frames
from video_assessment import detector_libraries, pair_boxes, pixels_hash

from aidetector.domain.models import BoundingBox


def localization_metrics(predictions, sources):
    result = {}
    for source in sources:
        panels = [row for row in predictions if row["video"] == source["video"]]
        result[source["video"]] = {}
        for threshold in (0.1, 0.25):
            targets = matched = unmatched = 0
            for row in panels:
                boxes = [
                    BoundingBox(*box)
                    for box, confidence in zip(
                        row["boxes"], row["confidence"], strict=True
                    )
                    if confidence >= threshold
                ]
                pairs = pair_boxes(boxes, row["truth"])
                targets += len(row["truth"])
                matched += len(pairs)
                unmatched += len(boxes) - len(pairs)
            result[source["video"]][str(threshold)] = {
                "frames": len(panels),
                "annotated_targets": targets,
                "matched_targets": matched,
                "missed_targets": targets - matched,
                "unmatched_predictions": unmatched,
                "annotated_recall": matched / targets,
            }
    return result


def evaluate(args):
    from ultralytics import YOLO

    protocol = json.loads(args.protocol.read_text())
    manifest_path = args.oracle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["contract"]["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Oracle panel does not match the frozen protocol")
    provenance = {
        "protocol_sha256": digest(args.protocol),
        "manifest_sha256": digest(manifest_path),
        "model_sha256": digest(args.model),
        "libraries": detector_libraries(),
        "device": args.device,
        "imgsz": 640,
        "quantize": 16,
        "confidence": 0.1,
        "iou": 0.7,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    cache_path = args.output / "predictions.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached["provenance"] != provenance:
            raise ValueError("Cached localization provenance changed; use a new output")
        predictions = cached["predictions"]
    else:
        model = YOLO(str(args.model))
        cow_classes = [key for key, name in model.names.items() if name == "cow"]
        if not cow_classes:
            raise ValueError(f"Model does not expose cow class: {model.names}")
        predictions = []
        started = time.perf_counter()
        for source in protocol["videos"]:
            if digest(Path(source["path"])) != source["sha256"]:
                raise ValueError(f"Video source changed: {source['path']}")
            selected = [
                row for row in manifest["rows"] if row.get("video") == source["video"]
            ]
            frame_indices = {row["frame"] for row in selected}
            for index, _, image in source_frames(source, frame_indices):
                truth = [
                    {"cow": row["cow"], "box": row["box"]}
                    for row in selected
                    if row["frame"] == index
                ]
                result = model.predict(
                    image,
                    classes=cow_classes,
                    imgsz=640,
                    quantize=16,
                    conf=0.1,
                    iou=0.7,
                    device=args.device,
                    verbose=False,
                )[0]
                boxes = result.boxes.xyxy.cpu().tolist()
                confidences = result.boxes.conf.cpu().tolist()
                predictions.append(
                    {
                        "video": source["video"],
                        "frame": index,
                        "pixels_sha256": pixels_hash(image),
                        "truth": truth,
                        "boxes": boxes,
                        "confidence": confidences,
                    }
                )
                if index == 0:
                    left = annotated_panel(
                        image,
                        [row["box"] for row in truth],
                        [f"GT {row['cow']}" for row in truth],
                        f"{source['video']}: original publisher labels",
                        (0, 230, 0),
                    )
                    right = annotated_panel(
                        image,
                        np.asarray(boxes).astype(int),
                        [f"YOLO {confidence:.2f}" for confidence in confidences],
                        "Author YOLOv8s / 640px / confidence >= 0.10",
                        (0, 190, 255),
                    )
                    cv2.imwrite(
                        str(args.output / f"{source['video']}-first-frame.jpg"),
                        np.concatenate((left, right), axis=1),
                    )
            print(
                json.dumps({"video": source["video"], "frames": len(frame_indices)}),
                flush=True,
            )
        write_json(
            cache_path,
            {
                "provenance": provenance,
                "predictions": predictions,
                "seconds_including_decode": time.perf_counter() - started,
            },
        )
    result = localization_metrics(predictions, protocol["videos"])
    summary = {
        "purpose": "Author detector external-scene regression; publisher annotations are not exhaustive, so unmatched predictions are not labelled false positives",
        "provenance": provenance,
        "model": str(args.model),
        "videos": result,
    }
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("research/cow_identity/ethz_protocol.json"),
    )
    parser.add_argument("--oracle", type=Path, default=Path(".cache/cow-ethz-oracle"))
    parser.add_argument(
        "--model", type=Path, default=Path(".cache/cow-detectors/ethz-yolov8s.pt")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/cow-ethz-localization")
    )
    parser.add_argument("--device", default="mps")
    evaluate(parser.parse_args())
