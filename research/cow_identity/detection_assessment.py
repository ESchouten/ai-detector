"""Cached, fixed-split cow localization comparison using verified numeric labels."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

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

PROTOCOL = Path(__file__).with_name("detection_protocol.json")


def load_panel(args, protocol):
    if digest(args.video) != protocol["video_sha256"]:
        raise ValueError("Unexpected source video")
    records, metadata = annotations(args)
    if metadata["source_sha256"] != protocol["source_annotations_sha256"]:
        raise ValueError("Unexpected source annotations")
    split = protocol["splits"][args.split]
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frames = []
    try:
        for second in range(split["start"], split["stop"], split["step"]):
            frame_id, image = read_frame(capture, second, fps)
            frames.append(
                {
                    "second": second,
                    "frame": frame_id,
                    "image": image,
                    "truth": truth_at(
                        records, frame_id, image.shape[1], image.shape[0]
                    ),
                    "sha256": pixels_hash(image),
                }
            )
    finally:
        capture.release()
    return frames


def predict(args, frames):
    from ultralytics import YOLO

    provenance = {
        "version": 1,
        "model": digest(args.model),
        "images": [frame["sha256"] for frame in frames],
        "libraries": detector_libraries(),
        "device": args.device,
        "imgsz": 640,
        "quantize": 16,
        "conf": 0.05,
        "iou": 0.7,
        "cow_class": args.cow_class,
    }
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cache = args.cache / f"localization-{key}.json"
    if cache.exists():
        return json.loads(cache.read_text()), True
    model = YOLO(str(args.model))
    if args.cow_class not in model.names:
        raise ValueError(f"Unknown cow class {args.cow_class}: {model.names}")
    predictions = []
    started = time.perf_counter()
    for frame in frames:
        tick = time.perf_counter()
        result = model.predict(
            frame["image"],
            classes=[args.cow_class],
            imgsz=640,
            quantize=16,
            conf=0.05,
            iou=0.7,
            device=args.device,
            verbose=False,
        )[0]
        predictions.append(
            {
                "second": frame["second"],
                "boxes": result.boxes.xyxy.cpu().tolist(),
                "confidence": result.boxes.conf.cpu().tolist(),
                "elapsed": time.perf_counter() - tick,
            }
        )
    backend = model.predictor.model
    value = {
        "provenance": provenance,
        "predictions": predictions,
        "elapsed": time.perf_counter() - started,
        "backend": {"device": str(backend.device), "fp16": backend.fp16},
        "class_names": model.names,
    }
    write_json(cache, value)
    return value, False


def boxes_above(prediction, confidence):
    return [
        BoundingBox(*xyxy)
        for xyxy, score in zip(
            prediction["boxes"], prediction["confidence"], strict=True
        )
        if score >= confidence
    ]


def score(frames, predictions, confidence):
    counts = {"true_positive": 0, "false_positive": 0, "false_negative": 0}
    for frame, prediction in zip(frames, predictions, strict=True):
        boxes = boxes_above(prediction, confidence)
        matches = pair_boxes(boxes, frame["truth"])
        counts["true_positive"] += len(matches)
        counts["false_positive"] += len(boxes) - len(matches)
        counts["false_negative"] += len(frame["truth"]) - len(matches)
    tp, fp, fn = (
        counts[key] for key in ("true_positive", "false_positive", "false_negative")
    )
    return {
        "confidence": confidence,
        **counts,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn),
        "f1": 2 * tp / (2 * tp + fp + fn),
    }


def evaluate(args):
    protocol = json.loads(args.protocol.read_text())
    frames = load_panel(args, protocol)
    value, cached = predict(args, frames)
    metrics = [
        score(frames, value["predictions"], threshold)
        for threshold in protocol["selection"]["thresholds"]
    ]
    result = {
        "protocol_sha256": digest(args.protocol),
        "split": args.split,
        "model": str(args.model),
        "frames": len(frames),
        "cache_reused": cached,
        "metrics": metrics,
        "calibration_choice": max(
            metrics, key=lambda row: (row["f1"], row["precision"], row["confidence"])
        )
        if args.split == "calibration"
        else None,
        "inference": value,
    }
    write_json(args.output, result)
    print(json.dumps({key: val for key, val in result.items() if key != "inference"}))


def prepare(args):
    protocol = json.loads(args.protocol.read_text())
    for split, destination in (("train", "train"), ("calibration", "val")):
        frames = load_panel(
            SimpleNamespace(**(vars(args) | {"split": split})), protocol
        )
        images, labels = (
            args.output / "images" / destination,
            args.output / "labels" / destination,
        )
        images.mkdir(parents=True, exist_ok=True)
        labels.mkdir(parents=True, exist_ok=True)
        for frame in frames:
            stem = str(frame["frame"])
            image = frame["image"]
            cv2.imwrite(
                str(images / f"{stem}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 95]
            )
            height, width = image.shape[:2]
            lines = []
            for row in frame["truth"]:
                x1, y1, x2, y2 = row["box"]
                lines.append(
                    f"0 {(x1 + x2) / (2 * width)} {(y1 + y2) / (2 * height)} "
                    f"{(x2 - x1) / width} {(y2 - y1) / height}"
                )
            (labels / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    (args.output / "data.yaml").write_text(
        f"path: {args.output.resolve()}\ntrain: images/train\nval: images/val\nnames: [cow]\n"
    )
    write_json(args.output / "protocol.json", protocol)
    print(f"Prepared {args.output / 'data.yaml'}")


def train(args):
    from ultralytics import YOLO

    protocol = json.loads(args.protocol.read_text())
    if json.loads((args.output / "protocol.json").read_text()) != protocol:
        raise ValueError("Prepared training data must match the frozen protocol")
    run = args.cache.resolve() / "training" / (args.run_name or args.model.stem)
    if run.exists():
        raise ValueError(f"Preserve the previous training run: {run}")
    settings = dict(protocol["training_if_needed"])
    settings.pop("initial_model")
    YOLO(str(args.model)).train(
        data=str(args.output / "data.yaml"),
        project=str(run.parent),
        name=run.name,
        plots=False,
        cache="ram",
        **settings,
    )
    write_json(
        run / "provenance.json",
        {
            "protocol_sha256": digest(args.protocol),
            "initial_model_sha256": digest(args.model),
            "best_model_sha256": digest(run / "weights/best.pt"),
            "libraries": detector_libraries(),
            "note": "Only class cow is fitted; all calf identity labels are discarded.",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("evaluate", "prepare", "train"))
    for field in ("video", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--run-name")
    parser.add_argument("--cache", type=Path, default=Path(".cache/cow-detectors"))
    parser.add_argument("--device", default="mps")
    parser.add_argument("--cow-class", type=int, default=0)
    parser.add_argument(
        "--split",
        choices=("train", "calibration", "development", "development_later"),
        default="calibration",
    )
    args = parser.parse_args()
    if args.action in {"evaluate", "train"}:
        if args.model is None:
            parser.error(f"{args.action} requires --model")
        (evaluate if args.action == "evaluate" else train)(args)
    else:
        prepare(args)


if __name__ == "__main__":
    main()
