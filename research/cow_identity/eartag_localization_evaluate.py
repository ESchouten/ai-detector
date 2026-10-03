"""Fixed full-frame head/tag localization, with raw inference before scoring."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from eartag_localization_training import RESULTS, ROOT, checked, digest, sdk, write

PREPARATION = RESULTS / "localization-preparation.json"
TAGS = RESULTS / "ownership-subset-inventory.json"
HEADS = RESULTS / "ownership-oracle-draft.json"
TRAINING = RESULTS / "localization-training.json"
TRAINING_SHA = "a88272aba67d68ac58582d5183ca32c6a373a9d6c39a307db8676c264bdecb10"


def freeze(path):
    import cv2
    import ultralytics
    from video_assessment import pixels_hash

    if path.exists() or digest(TRAINING) != TRAINING_SHA:
        raise ValueError("Preserve previous freeze and fixed final training result")
    training = json.loads(TRAINING.read_text())
    if training["status"] != "COMPLETE_FIXED_TRAINING_ONLY":
        raise ValueError("Final epoch20 model is unavailable")
    checkpoint = Path(training["selected_checkpoint"])
    if digest(checkpoint) != training["selected_sha256"]:
        raise ValueError("Selected final EMA changed")
    rows = []
    for row in json.loads(PREPARATION.read_text())["rows"]:
        if row["proposed_split"] not in {"development", "evaluation"}:
            continue
        image_path = ROOT / row["image"]
        if digest(image_path) != row["image_sha256"]:
            raise ValueError("Scene source changed")
        image = cv2.imread(str(image_path))
        if image is None or image.shape[:2] != (row["height"], row["width"]):
            raise ValueError("Source decoding differs")
        rows.append(
            {
                "id": row["id"],
                "panel": row["proposed_split"],
                "image": row["image"],
                "image_sha256": row["image_sha256"],
                "shape": list(image.shape),
                "pixels_sha256": pixels_hash(image),
            }
        )
    if len(rows) != 11 or sum(r["panel"] == "development" for r in rows) != 3:
        raise ValueError("Expected frozen3development/8outdoor images")
    sdkroot = Path(ultralytics.__file__).parent
    files = {
        Path(__file__),
        Path(__file__).with_name("test_eartag_localization_evaluate.py"),
        Path(__file__).with_name("eartag_localization_training.py"),
        Path(__file__).with_name("video_assessment.py"),
        Path(__file__).with_name("benchmark.py"),
        ROOT / "detector/src/aidetector/domain/models.py",
        PREPARATION,
        TAGS,
        HEADS,
        Path(__file__).with_name("eartag_ownership_oracle_protocol.json"),
        TRAINING,
        checkpoint,
    }
    files.update(ROOT / row["image"] for row in rows)
    files.update(sdkroot.rglob("*.py"))
    files.update(sdkroot.rglob("*.yaml"))
    write(
        path,
        {
            "status": "FROZEN_BEFORE_FIRST_WHOLEFRAME_INFERENCE",
            "python": sys.version,
            "files": {str(p): digest(p) for p in sorted(files)},
            "libraries": {
                n: importlib.metadata.version(n)
                for n in (
                    "torch",
                    "torchvision",
                    "ultralytics",
                    "numpy",
                    "opencv-python",
                    "lap",
                )
            },
            "checkpoint": str(checkpoint),
            "rows": rows,
            "prediction": {
                "device": "mps",
                "imgsz": 1280,
                "batch": 1,
                "quantize": 32,
                "conf": 0.25,
                "iou": 0.7,
                "rect": True,
                "augment": False,
                "agnostic_nms": False,
                "max_det": 300,
                "verbose": False,
                "save": False,
            },
            "scoring": "All44publisher tags:11development+33outdoor, one-to-one max-cardinality IoU>=.5. All12 reviewed development heads, including uncertain/clipped heads; no outdoor head precision without labels. Every unmatched prediction retained as conservative extra. Fixed tag min-side bins<16/16–31.99/32–63.99/>=64 in native and actual1280-letterbox input pixels. No threshold/model selection, no OCR/ownership/biological names.",
            "limitations": "Scene groups are not certified animal/farm/date independent. Publisher tag annotation completeness may be imperfect; unmatched means unmatched-to-publisher, not verified physical false alarm. Raw predictions are immutable before truth scoring. No outdoor head/body labels are invented.",
        },
    )


def inference(protocol, output):
    import cv2
    import torch
    from ultralytics import YOLO
    from video_assessment import pixels_hash

    document = checked(protocol)
    if output.exists():
        raise ValueError("Preserve previous raw outputs")
    sdk()
    model = YOLO(document["checkpoint"])
    if model.names != {0: "head", 1: "ear_tag"}:
        raise ValueError("Unexpected learned class mapping")
    shapes = []

    def input_shape(module, args):
        if args and isinstance(args[0], torch.Tensor):
            shapes.append(list(args[0].shape))

    handle = model.model.register_forward_pre_hook(input_shape)
    rows = []
    started = time.perf_counter()
    try:
        for row in document["rows"]:
            image = cv2.imread(str(ROOT / row["image"]))
            if image is None or pixels_hash(image) != row["pixels_sha256"]:
                raise ValueError("Frozen source pixels changed")
            shapes.clear()
            tick = time.perf_counter()
            result = model.predict(source=image, **document["prediction"])[0]
            if not shapes or shapes[-1][0:2] != [1, 3]:
                raise ValueError("Missing actual batch1 image-tensor dimensions")
            backend = model.predictor.model
            if backend.device.type != "mps" or backend.fp16:
                raise ValueError("Actual inference is not MPS FP32")
            boxes = [
                {"class": int(cls), "confidence": float(conf), "xyxy": xyxy}
                for xyxy, conf, cls in zip(
                    result.boxes.xyxy.cpu().tolist(),
                    result.boxes.conf.cpu().tolist(),
                    result.boxes.cls.cpu().tolist(),
                    strict=True,
                )
            ]
            rows.append(
                {
                    **row,
                    "boxes": boxes,
                    "input_shape": shapes[-1],
                    "seconds": time.perf_counter() - tick,
                    "device": str(backend.device),
                    "fp16": bool(backend.fp16),
                }
            )
    finally:
        handle.remove()
    write(
        output,
        {
            "status": "COMPLETE_RAW_BEFORE_SCORE",
            "protocol_sha256": digest(protocol),
            "seconds": time.perf_counter() - started,
            "rows": rows,
        },
    )


def validate_raw(document, raw, protocol_sha):
    if (
        raw["status"] != "COMPLETE_RAW_BEFORE_SCORE"
        or raw["protocol_sha256"] != protocol_sha
    ):
        raise ValueError("Raw prediction protocol/completion differs")
    if len(raw["rows"]) != len(document["rows"]):
        raise ValueError("Incomplete raw image set")
    for expected, actual in zip(document["rows"], raw["rows"], strict=True):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("Raw source order/pixels/panel changed")
        height, width = actual["shape"][:2]
        for box in actual["boxes"]:
            x1, y1, x2, y2 = box["xyxy"]
            if (
                box["class"] not in {0, 1}
                or not 0.25 <= box["confidence"] <= 1
                or not all(math.isfinite(v) for v in box["xyxy"])
                or not 0 <= x1 < x2 <= width
                or not 0 <= y1 < y2 <= height
            ):
                raise ValueError("Malformed native prediction")


def matches(boxes, truth):
    from video_assessment import pair_boxes

    return pair_boxes(
        [
            SimpleNamespace(
                **dict(zip(("x1", "y1", "x2", "y2"), b["xyxy"], strict=True))
            )
            for b in boxes
        ],
        [{"box": t["xyxy"]} for t in truth],
    )


def counts(boxes, truth):
    pairing = matches(boxes, truth)
    tp, total, predicted = len(pairing), len(truth), len(boxes)
    return {
        "truth": total,
        "predicted": predicted,
        "matched": tp,
        "missed": total - tp,
        "unmatched_predictions": predicted - tp,
        "pairs": pairing,
    }


def size_bin(value):
    return (
        "<16"
        if value < 16
        else "16–32"
        if value < 32
        else "32–64"
        if value < 64
        else ">=64"
    )


def score(protocol, raw_path, output):
    document = checked(protocol)
    raw = json.loads(raw_path.read_text())
    validate_raw(document, raw, digest(protocol))
    if output.exists():
        raise ValueError("Preserve previous score")
    # Truth enters only after all11 immutable raw rows pass provenance checks.
    tags = {row["id"]: row for row in json.loads(TAGS.read_text())["rows"]}
    heads = {row["id"]: row for row in json.loads(HEADS.read_text())["rows"]}
    details, panels = [], defaultdict(lambda: defaultdict(int))
    bins = defaultdict(lambda: {"truth": 0, "matched": 0})
    for row in raw["rows"]:
        predictions = [b for b in row["boxes"] if b["class"] == 1]
        truth = tags[row["id"]]["tags"]
        result = counts(predictions, truth)
        for key, value in result.items():
            if key != "pairs":
                panels[row["panel"]][key] += value
        gain = min(
            row["input_shape"][2] / row["shape"][0],
            row["input_shape"][3] / row["shape"][1],
        )
        matched = set(result["pairs"].values())
        for index, tag in enumerate(truth):
            b = tag["xyxy"]
            size = min(b[2] - b[0], b[3] - b[1])
            for unit, factor in (("native", 1), ("input", gain)):
                key = f"{row['panel']}/{unit}/{size_bin(size * factor)}"
                bins[key]["truth"] += 1
                bins[key]["matched"] += int(index in matched)
        detail = {
            "id": row["id"],
            "panel": row["panel"],
            "tag": result,
            "input_gain": gain,
        }
        if row["panel"] == "development":
            detail["head"] = counts(
                [b for b in row["boxes"] if b["class"] == 0], heads[row["id"]]["heads"]
            )
        details.append(detail)
    if panels["development"]["truth"] != 11 or panels["evaluation"]["truth"] != 33:
        raise ValueError("Publisher tag denominator differs")
    head_totals = {
        key: sum(row.get("head", {}).get(key, 0) for row in details)
        for key in ("truth", "predicted", "matched", "missed", "unmatched_predictions")
    }
    if head_totals["truth"] != 12:
        raise ValueError("Reviewed development head denominator differs")
    write(
        output,
        {
            "status": "COMPLETE_FIXED_WHOLEFRAME_LOCALIZATION",
            "protocol_sha256": digest(protocol),
            "raw_sha256": digest(raw_path),
            "panels": dict(panels),
            "development_heads": head_totals,
            "tag_size_bins": dict(bins),
            "details": details,
            "scoring": document["scoring"],
            "limitations": document["limitations"],
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "infer", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.protocol)
    elif args.command == "infer" and args.output:
        inference(args.protocol, args.output)
    elif args.command == "score" and args.raw and args.output:
        score(args.protocol, args.raw, args.output)
    else:
        parser.error("infer requires--output; score requires--raw and--output")
