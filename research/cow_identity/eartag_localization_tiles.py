"""Fixed source-resolution tile control of the completed head/tag model."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import math
import sys
import time
from pathlib import Path

from eartag_localization_evaluate import HEADS, TAGS, counts, validate_raw
from eartag_localization_training import RESULTS, ROOT, checked, digest, sdk, write

BASE = Path(__file__).with_name("eartag_localization_evaluate_protocol.json")
BASE_RAW = RESULTS / "localization-raw.json"
BASE_SCORE = RESULTS / "localization-score.json"
SIDE, STRIDE = 1280, 1024
KEYS = ("truth", "predicted", "matched", "missed", "unmatched_predictions")


def origins(length: int) -> list[int]:
    if length <= 0:
        raise ValueError("Positive source dimension required")
    if length <= SIDE:
        return [0]
    last = length - SIDE
    return sorted({*range(0, last + 1, STRIDE), last})


def tiles(shape) -> list[list[int]]:
    height, width = shape[:2]
    return [
        [x, y, min(x + SIDE, width), min(y + SIDE, height)]
        for y in origins(height)
        for x in origins(width)
    ]


def shifted(box, tile):
    x, y, _, _ = tile
    a, b, c, d = box["xyxy"]
    return {**box, "xyxy": [a + x, b + y, c + x, d + y]}


def merge(boxes):
    """Public class-aware CPU NMS; preserve original order among survivors."""
    import torch
    from torchvision.ops import batched_nms

    if not boxes:
        return [], []
    keep = batched_nms(
        torch.tensor([b["xyxy"] for b in boxes], dtype=torch.float32),
        torch.tensor([b["confidence"] for b in boxes], dtype=torch.float32),
        torch.tensor([b["class"] for b in boxes], dtype=torch.int64),
        0.7,
    ).tolist()
    indices = sorted(keep)
    return [boxes[i] for i in indices], indices


def freeze(path):
    import torchvision
    import ultralytics

    if path.exists():
        raise ValueError("Preserve previous freeze")
    original = json.loads(BASE.read_text())
    raw = json.loads(BASE_RAW.read_text())
    validate_raw(original, raw, digest(BASE))
    rows = [{**r, "tiles": tiles(r["shape"])} for r in original["rows"]]
    if sum(len(r["tiles"]) for r in rows) != 55:
        raise ValueError("Expected exact55calls over unchanged11images")
    files = {
        Path(__file__),
        Path(__file__).with_name("test_eartag_localization_tiles.py"),
        Path(__file__).with_name("eartag_localization_tiles_guard.py"),
        Path(__file__).with_name("eartag_localization_evaluate.py"),
        Path(__file__).with_name("eartag_localization_training.py"),
        Path(__file__).with_name("video_assessment.py"),
        Path(__file__).with_name("benchmark.py"),
        ROOT / "detector/src/aidetector/domain/models.py",
        BASE,
        BASE_RAW,
        BASE_SCORE,
        TAGS,
        HEADS,
        Path(original["checkpoint"]),
    }
    files.update(ROOT / r["image"] for r in rows)
    for library in (ultralytics, torchvision):
        directory = Path(library.__file__).parent
        files.update(directory.rglob("*.py"))
        files.update(directory.rglob("*.yaml"))
        files.update(directory.rglob("*.so"))
    write(
        path,
        {
            "status": "FROZEN_BEFORE_TILE_INFERENCE",
            "scope": "Single exploratory input-scale control on already exposed11frames. No retraining, GT-centered crops, new image or threshold adjustment. All44tags/12developmentheads retained; outdoor heads lack truth and are not scored.",
            "python": sys.version,
            "libraries": {
                n: importlib.metadata.version(n)
                for n in (*original["libraries"], "psutil")
            },
            "files": {str(p): digest(p) for p in sorted(files)},
            "checkpoint": original["checkpoint"],
            "prediction": original["prediction"],
            "rows": rows,
            "tiling": {"side": SIDE, "stride": STRIDE, "calls": 55},
            "merge": "Every native1280tile in row-major order,20%overlap or greater at edge-anchor. SDK returns tile-native xyxy; add exact integer origin. No fullframe extra pass. Public torchvision CPU batched_nms IoU.7,class-aware on ALL mapped boxes; original tile/index order for ties is input to pinned CPU implementation, survivors restored to original order. No global output cap, weighted merge, clipping-away of tile-edge boxes or label-dependent selection. SDKper-tile max_det300 inherited; exact saturation aborts as incomplete instead of silently accepting truncation.",
            "parity": "The3lowresframes each have one unmodified tile, same1280 SDKletterbox and settings. Require exact original local boxes,inputshape AND postmerge boxes before any truth score; otherwise preserve FAILED_LOWRES_PARITY. Baseline fullframe counts replay exactly before tile comparison.",
            "limits": {
                "seconds": 180,
                "rss_bytes": 8 * 1024**3,
                "mps_driver_bytes": 8 * 1024**3,
            },
            "limitations": "No independent heldout result. Tile context differs and can create extra fragment/background predictions. Publisher tag completeness uncertain; extras remain errors. Native lowresolution pixels cannot recover missing detail. This does not test OCR, work-number semantics or animal ownership.",
        },
    )


def tile_prediction(model, image, tile, settings, shapes):
    x1, y1, x2, y2 = tile
    crop = image[y1:y2, x1:x2]
    shapes.clear()
    result = model.predict(source=crop, **settings)[0]
    backend = model.predictor.model
    if backend.device.type != "mps" or backend.fp16:
        raise ValueError("Require actual MPSFP32")
    if not shapes or shapes[-1][:2] != [1, 3]:
        raise ValueError("Missing actual batch1 inputshape")
    boxes = [
        {"class": int(cls), "confidence": float(conf), "xyxy": xyxy}
        for xyxy, conf, cls in zip(
            result.boxes.xyxy.cpu().tolist(),
            result.boxes.conf.cpu().tolist(),
            result.boxes.cls.cpu().tolist(),
            strict=True,
        )
    ]
    if len(boxes) >= settings["max_det"]:
        raise ValueError("Saturated per-tile max_det; retain incomplete failure")
    return {"native_xyxy": tile, "input_shape": shapes[-1], "boxes": boxes}


def inference(protocol, output):
    import cv2
    import torch
    from ultralytics import YOLO
    from video_assessment import pixels_hash

    document = checked(protocol)
    if output.exists():
        raise ValueError("Preserve prior tile outputs")
    sdk()
    model = YOLO(document["checkpoint"])
    if model.names != {0: "head", 1: "ear_tag"}:
        raise ValueError("Frozen class mapping differs")
    shapes, rows = [], []

    def shape(module, args):
        if args and isinstance(args[0], torch.Tensor):
            shapes.append(list(args[0].shape))

    started = time.perf_counter()
    handle = model.model.register_forward_pre_hook(shape)
    try:
        for row in document["rows"]:
            image = cv2.imread(str(ROOT / row["image"]))
            if image is None or pixels_hash(image) != row["pixels_sha256"]:
                raise ValueError("Exact source pixels changed")
            tick = time.perf_counter()
            calls = [
                tile_prediction(model, image, tile, document["prediction"], shapes)
                for tile in row["tiles"]
            ]
            mapped = [
                shifted(box, call["native_xyxy"])
                for call in calls
                for box in call["boxes"]
            ]
            boxes, keep = merge(mapped)
            rows.append(
                {
                    **row,
                    "tile_outputs": calls,
                    "mapped_boxes": mapped,
                    "kept_indices": keep,
                    "boxes": boxes,
                    "seconds": time.perf_counter() - tick,
                }
            )
            write(
                output,
                {
                    "status": "INCOMPLETE_TILE_INFERENCE",
                    "protocol_sha256": digest(protocol),
                    "rows": rows,
                },
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


def validate_tiles(document, raw, protocol_sha):
    validate_raw(document, raw, protocol_sha)
    original = {r["id"]: r for r in json.loads(BASE_RAW.read_text())["rows"]}
    for row in raw["rows"]:
        if [c["native_xyxy"] for c in row["tile_outputs"]] != row["tiles"]:
            raise ValueError("Missing/reordered tile outputs")
        for call in row["tile_outputs"]:
            x1, y1, x2, y2 = call["native_xyxy"]
            for box in call["boxes"]:
                a, b, c, d = box["xyxy"]
                if not (
                    0 <= a < c <= x2 - x1
                    and 0 <= b < d <= y2 - y1
                    and 0.25 <= box["confidence"] <= 1
                    and box["class"] in {0, 1}
                    and all(math.isfinite(v) for v in box["xyxy"])
                ):
                    raise ValueError("Invalid local geometry/confidence/class")
        mapped = [
            shifted(b, c["native_xyxy"])
            for c in row["tile_outputs"]
            for b in c["boxes"]
        ]
        merged, keep = merge(mapped)
        if (
            mapped != row["mapped_boxes"]
            or merged != row["boxes"]
            or keep != row["kept_indices"]
        ):
            raise ValueError("Native mapping or public merge differs")
        if row["panel"] == "development":
            baseline, call = original[row["id"]], row["tile_outputs"][0]
            if (
                len(row["tile_outputs"]) != 1
                or call["boxes"] != baseline["boxes"]
                or call["input_shape"] != baseline["input_shape"]
                or row["boxes"] != baseline["boxes"]
            ):
                return False
    return True


def scored(rows):
    tags = {r["id"]: r["tags"] for r in json.loads(TAGS.read_text())["rows"]}
    heads = {r["id"]: r["heads"] for r in json.loads(HEADS.read_text())["rows"]}
    details = []
    for row in rows:
        detail = {
            "id": row["id"],
            "panel": row["panel"],
            "tag": counts(
                [b for b in row["boxes"] if b["class"] == 1], tags[row["id"]]
            ),
        }
        if row["panel"] == "development":
            detail["head"] = counts(
                [b for b in row["boxes"] if b["class"] == 0], heads[row["id"]]
            )
        details.append(detail)
    panels = {
        p: {k: sum(d["tag"][k] for d in details if d["panel"] == p) for k in KEYS}
        for p in ("development", "evaluation")
    }
    head = {k: sum(d.get("head", {}).get(k, 0) for d in details) for k in KEYS}
    if (
        panels["development"]["truth"] != 11
        or panels["evaluation"]["truth"] != 33
        or head["truth"] != 12
    ):
        raise ValueError("All44tags/12heads required")
    return {"panels": panels, "development_heads": head, "details": details}


def score(protocol, raw_path, output):
    if output.exists():
        raise ValueError("Preserve prior score")
    document, raw = checked(protocol), json.loads(raw_path.read_text())
    if not validate_tiles(document, raw, digest(protocol)):
        write(
            output,
            {
                "status": "FAILED_LOWRES_PARITY",
                "protocol_sha256": digest(protocol),
                "raw_sha256": digest(raw_path),
                "scores": None,
            },
        )
        return
    baseline = json.loads(json.dumps(scored(json.loads(BASE_RAW.read_text())["rows"])))
    previous = json.loads(BASE_SCORE.read_text())
    old_details = copy.deepcopy(previous["details"])
    for row in old_details:
        row.pop("input_gain")
    if baseline != {
        "panels": previous["panels"],
        "development_heads": previous["development_heads"],
        "details": old_details,
    }:
        raise ValueError("Original fullframe counters/pairing changed")
    write(
        output,
        {
            "status": "COMPLETE_FIXED_TILE_CONTROL",
            "protocol_sha256": digest(protocol),
            "raw_sha256": digest(raw_path),
            "lowres_exact_parity": True,
            "original_counter_parity": True,
            "baseline": baseline,
            "tiled": scored(raw["rows"]),
            "scope": document["scope"],
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
        parser.error("infer requires--output; score requires--raw/--output")
