"""Fixed 64-tag OBB localization, unchanged readers and complete strict scoring."""

import argparse
import importlib.metadata
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from eartag_ocr import (
    DATA_MANIFEST,
    match_polygons,
    polygon,
    read_image,
    score_image,
    totals,
)

ROOT = Path(__file__).parent
TRAINING_PROTOCOL = ROOT / "eartag_obb_training_protocol.json"
TRAINING_REPORT = ROOT / "results/2026-10-03/ear-tags/obb-training.json"
OCR_PROTOCOL = ROOT / "eartag_ocr_protocol.json"
READER_PROTOCOL = ROOT / "eartag_trocr_cpu_evaluation_protocol.json"
CROPS = Path(".cache/cow-ear-tags/obb-pilot-crops")


def freeze(args):
    from eartag_obb_training import validate
    from eartag_trocr_cpu_evaluation import final_checkpoint

    training = validate(TRAINING_PROTOCOL)
    ocr = json.loads(OCR_PROTOCOL.read_text())
    reader = json.loads(READER_PROTOCOL.read_text())
    _, reader_report, checkpoint, _ = final_checkpoint(reader)
    paths = [
        Path(__file__),
        ROOT / "test_eartag_obb_evaluation.py",
        TRAINING_PROTOCOL,
        OCR_PROTOCOL,
        READER_PROTOCOL,
        reader_report,
    ]
    paths.extend(Path(p) for p in checkpoint["checkpoint_files"])
    write_json(
        args.protocol,
        {
            "scope": "Same frozen 64 development tag images, all157 original publisher lines. Final OBB detector only, native confidence.25/NMSIoU.7/max300 fixed before predictions. Compare unchanged smallRapidOCR and correctedTrOCR on EXACT same predicted crops, plus existing fixed .95 literal agreement; no model/threshold selection or calibration/reserved images.",
            "files": {
                **training["files"],
                **ocr["files"],
                **reader["files"],
                **{str(p): digest(p) for p in paths},
            },
            "libraries": {
                "detector": training["libraries"],
                "ocr": ocr["libraries"],
                "reader": reader["inference_libraries"],
            },
            "training_protocol_sha256": digest(TRAINING_PROTOCOL),
            "training_report": str(TRAINING_REPORT),
            "reader_protocol_sha256": digest(READER_PROTOCOL),
            "reader_training_report_sha256": digest(reader_report),
            "raw_input": ocr["raw_input"],
            "ocr_params": ocr["params"],
            "truth_sha256": digest(DATA_MANIFEST),
            "detector": {
                "device": "mps",
                "quantize": 32,
                "imgsz": 320,
                "conf": 0.25,
                "iou": 0.7,
                "max_det": 300,
                "verbose": False,
            },
            "crop": "Preserve native predicted quad for every score. Only reorder its same four corners with RapidOCR DBPostProcess.order_points_clockwise, then original SDK cubic warp/replicated border/tall-crop rotation and unchanged orientation classifier. No clipping, expansion, GT boxes, transcript, extra padding or manual orientation selection. Invalid/tiny crops remain explicit rejected readings, never removed from detector counts.",
            "reader": "Same original smallRapidOCR recognition and final correctedCPU-trained TrOCR, FP32MPS, greedymax32/batch4. Raw outputs on every valid predicted crop; confidence scales never mixed. Original RapidOCR score>=.95 plus exact nonempty literal equality is the only agreement gate.",
            "score": "Original cardinality-first unique polygonIoU>=.5, literal strip only. All64 images/all157 lines including missed and extra predictions. Fulltag requires all correct/no extras. Publish detector geometry plus both raw readers, RapidOCR.95 and exactagreement; no retrospective selector.",
        },
    )


def checked(path, family):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen OBB evaluation input changed: {name}")
    if {
        name: importlib.metadata.version(name) for name in value["libraries"][family]
    } != value["libraries"][family]:
        raise ValueError("Evaluation environment changed")
    if digest(DATA_MANIFEST) != value["truth_sha256"]:
        raise ValueError("Truth manifest changed")
    return value


def final_detector(frozen):
    report = json.loads(TRAINING_REPORT.read_text())
    if (
        not report["complete"]
        or report["error"] is not None
        or report["mode"] != "train"
        or report["protocol_sha256"] != frozen["training_protocol_sha256"]
        or report["steps"] != 1700
        or len(report["batches"]) != 1700
        or [row["epoch"] for row in report["history"]] != list(range(1, 21))
    ):
        raise ValueError("Only complete final original20epoch OBB training is eligible")
    path = Path(report["checkpoint"])
    expected = Path(".cache/cow-ear-tags/obb-training/train/weights/last.pt").resolve()
    if path.resolve() != expected or digest(path) != report["checkpoint_sha256"]:
        raise ValueError("Final native last.pt changed")
    return path, report


def validate_detection(raw, frozen, protocol_hash):
    expected = [
        (r["id"], r["image_sha256"], r["pixels_sha256"]) for r in frozen["raw_input"]
    ]
    actual = [(r["id"], r["image_sha256"], r["pixels_sha256"]) for r in raw["rows"]]
    if (
        not raw["complete"]
        or raw["error"] is not None
        or raw["protocol_sha256"] != protocol_hash
        or actual != expected
    ):
        raise ValueError("Require all64 exact ordered detector inputs")


def detect(args):
    from eartag_obb_training import sdk

    frozen = checked(args.protocol, "detector")
    torch, ultralytics = sdk()
    if not torch.backends.mps.is_available():
        raise ValueError("Require actual MPS inference")
    path, training = final_detector(frozen)
    started = time.perf_counter()
    model = ultralytics.YOLO(str(path))
    rows = []
    for source in frozen["raw_input"]:
        image, pixel_hash = read_image(source)
        tick = time.perf_counter()
        output = model.predict(image, **frozen["detector"])[0]
        if model.predictor.model.device.type != "mps" or model.predictor.model.fp16:
            raise ValueError("Actual detector must use MPS FP32")
        predictions = [
            {"index": i, "polygon": bounds, "detector_score": float(score)}
            for i, (bounds, score) in enumerate(
                zip(
                    output.obb.xyxyxyxy.cpu().tolist(),
                    output.obb.conf.cpu().tolist(),
                    strict=True,
                )
            )
        ]
        if any(
            not np.isfinite(r["polygon"]).all()
            or not math.isfinite(r["detector_score"])
            for r in predictions
        ):
            raise ValueError("Nonfinite detector output")
        rows.append(
            {
                **source,
                "inference_bgr_pixels_sha256": pixel_hash,
                "predictions": predictions,
                "seconds": time.perf_counter() - tick,
            }
        )
    write_json(
        args.output,
        {
            "protocol_sha256": digest(args.protocol),
            "complete": True,
            "error": None,
            "actual_device": "mps",
            "precision": "float32",
            "checkpoint_sha256": training["checkpoint_sha256"],
            "training_report_sha256": digest(TRAINING_REPORT),
            "rows": rows,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )


def crop_reading(engine, image, prediction, key, index):
    from rapidocr.utils.process_img import get_rotate_crop_image

    result = {
        "id": key,
        "index": index,
        "polygon": prediction["polygon"],
        "issue": None,
    }
    points = polygon(prediction["polygon"])
    if points is None:
        return {**result, "issue": "invalid polygon"}, {
            **result,
            "text": "",
            "score": None,
        }
    ordered = engine.text_det.postprocess_op.order_points_clockwise(points.copy())
    sides = [
        int(
            max(
                np.linalg.norm(ordered[a] - ordered[b]),
                np.linalg.norm(ordered[c] - ordered[d]),
            )
        )
        for a, b, c, d in ((0, 1, 2, 3), (0, 3, 1, 2))
    ]
    if min(sides) < 1:
        return {**result, "issue": "subpixel crop"}, {
            **result,
            "text": "",
            "score": None,
        }
    crop = get_rotate_crop_image(image, ordered)
    rotated, orientation = engine.cls_and_rotate([crop])
    path = CROPS / f"{key}-{index}.png"
    if not cv2.imwrite(str(path), rotated[0]):
        raise OSError("Could not cache exact reader input")
    reading = engine.recognize_txt(rotated)
    if (
        reading.txts is None
        or reading.scores is None
        or len(reading.txts) != 1
        or not math.isfinite(float(reading.scores[0]))
    ):
        raise ValueError("Expected one finite raw reading per line")
    prepared = {
        **result,
        "path": str(path),
        "sha256": digest(path),
        "crop_polygon": ordered.tolist(),
        "orientation": str(orientation.cls_res[0][0]),
        "shape": list(rotated[0].shape),
    }
    return prepared, {
        **result,
        "crop_sha256": prepared["sha256"],
        "text": str(reading.txts[0]),
        "score": float(reading.scores[0]),
    }


def read_rapid(args):
    import onnxruntime
    from rapidocr import RapidOCR

    frozen = checked(args.protocol, "ocr")
    detection = json.loads(args.raw.read_text())
    validate_detection(detection, frozen, digest(args.protocol))
    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(2)
    started = time.perf_counter()
    engine = RapidOCR(params=frozen["ocr_params"])
    providers = {
        name: getattr(engine, name).session.session.get_providers()
        for name in ("text_cls", "text_rec")
    }
    if any(value != ["CPUExecutionProvider"] for value in providers.values()):
        raise ValueError("Require frozen CPU reader providers")
    CROPS.mkdir()
    rows, prepared = [], []
    for frame in detection["rows"]:
        image, actual = read_image(frame)
        if actual != frame["inference_bgr_pixels_sha256"]:
            raise ValueError("Reader and detector must see identical source pixels")
        for index, prediction in enumerate(frame["predictions"]):
            crop, reading = crop_reading(engine, image, prediction, frame["id"], index)
            prepared.append(crop)
            rows.append(reading)
    manifest = {
        "protocol_sha256": digest(args.protocol),
        "detector_sha256": digest(args.raw),
        "complete": True,
        "rows": prepared,
    }
    write_json(CROPS / "manifest.json", manifest)
    write_json(
        args.output,
        {
            "protocol_sha256": digest(args.protocol),
            "detector_sha256": digest(args.raw),
            "crop_manifest_sha256": digest(CROPS / "manifest.json"),
            "complete": True,
            "error": None,
            "providers": providers,
            "rows": rows,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )


def read_trocr(args):
    import torch
    from eartag_trocr import load_model, new_report, processor
    from eartag_trocr_cpu_evaluation import final_checkpoint, generate_rows

    frozen = checked(args.protocol, "reader")
    if not torch.backends.mps.is_available():
        raise ValueError("Require MPS reader inference")
    torch.set_num_threads(2)
    data = json.loads((CROPS / "manifest.json").read_text())
    detection = json.loads(args.raw.read_text())
    validate_detection(detection, frozen, digest(args.protocol))
    validate_crop_rows(data["rows"], detection)
    if (
        not data["complete"]
        or data["protocol_sha256"] != digest(args.protocol)
        or data["detector_sha256"] != digest(args.raw)
    ):
        raise ValueError("Require complete exact detection-crop manifest")
    checkpoint, report_path, training, _ = final_checkpoint(
        json.loads(READER_PROTOCOL.read_text())
    )
    if digest(report_path) != frozen["reader_training_report_sha256"]:
        raise ValueError("Corrected reader checkpoint changed")
    report = new_report(args)
    report.update(
        rows=[],
        detector_sha256=digest(args.raw),
        crop_manifest_sha256=digest(CROPS / "manifest.json"),
        training_report_sha256=digest(report_path),
        model_files=training["checkpoint_files"],
    )
    started = time.perf_counter()
    model = load_model(checkpoint, "mps").eval()
    selected = [row for row in data["rows"] if row["issue"] is None]
    generate_rows(
        model, processor(), {"panels": {"oracle": [], "detected": selected}}, report
    )
    report.update(
        complete=len(report["rows"]) == len(selected),
        elapsed_seconds=time.perf_counter() - started,
    )
    write_json(args.output, report)


def validate_crop_rows(rows, detection):
    expected = [
        (frame["id"], i, row["polygon"])
        for frame in detection["rows"]
        for i, row in enumerate(frame["predictions"])
    ]
    actual = [(r["id"], r["index"], r["polygon"]) for r in rows]
    if actual != expected:
        raise ValueError(
            "Every original prediction must retain the same indexed geometry"
        )


def read_conditions(rapid, trocr):
    result = {
        name: []
        for name in ("rapid_raw", "rapid_0.95", "trocr_raw", "literal_agreement")
    }
    for row in rapid:
        key = (row["id"], row["index"])
        alternative = trocr.get(key)
        text = alternative["text"] if alternative is not None else ""
        prediction = {
            "polygon": row["polygon"],
            "text": row["text"],
            "score": row["score"],
        }
        result["rapid_raw"].append(prediction)
        result["trocr_raw"].append({**prediction, "text": text, "score": None})
        if row["score"] is not None and row["score"] >= 0.95:
            result["rapid_0.95"].append(prediction)
            if row["text"].strip() and row["text"].strip() == text.strip():
                result["literal_agreement"].append(prediction)
    return result


def validate_reader_crops(prepared, rapid, trocr):
    expected = [
        (r["id"], r["index"], r["polygon"], r["sha256"])
        for r in prepared
        if r["issue"] is None
    ]
    for rows in (rapid, trocr):
        actual = [
            (r["id"], r["index"], r["polygon"], r["crop_sha256"])
            for r in rows
            if r.get("issue") is None
        ]
        if actual != expected:
            raise ValueError("Both readers must use every identical prepared crop")


def score(args):
    frozen = checked(args.protocol, "ocr")
    detection = json.loads(args.raw.read_text())
    rapid = json.loads(args.rapid.read_text())
    trocr = json.loads(args.trocr.read_text())
    data = json.loads((CROPS / "manifest.json").read_text())
    validate_detection(detection, frozen, digest(args.protocol))
    _, training = final_detector(frozen)
    if detection["checkpoint_sha256"] != training["checkpoint_sha256"] or detection[
        "training_report_sha256"
    ] != digest(TRAINING_REPORT):
        raise ValueError("Detector provenance changed")
    for raw in (rapid, trocr):
        if (
            not raw["complete"]
            or raw["error"] is not None
            or raw["protocol_sha256"] != digest(args.protocol)
            or raw["detector_sha256"] != digest(args.raw)
            or raw["crop_manifest_sha256"] != digest(CROPS / "manifest.json")
        ):
            raise ValueError("Require complete same-crop raw readers before scoring")
    validate_crop_rows(rapid["rows"], detection)
    validate_crop_rows(data["rows"], detection)
    validate_reader_crops(data["rows"], rapid["rows"], trocr["rows"])
    if trocr["training_report_sha256"] != frozen["reader_training_report_sha256"]:
        raise ValueError("Corrected reader training provenance changed")
    truth = {r["id"]: r["lines"] for r in json.loads(DATA_MANIFEST.read_text())["rows"]}
    alternate = {(r["id"], r["index"]): r for r in trocr["rows"]}
    conditions = {name: [] for name in read_conditions([], {})}
    geometry = []
    for frame in detection["rows"]:
        key = frame["id"]
        matches = match_polygons(truth[key], frame["predictions"])
        geometry.append(
            {
                "id": key,
                "truth_lines": len(truth[key]),
                "predictions": len(frame["predictions"]),
                "matched": len(matches),
                "missed": len(truth[key]) - len(matches),
                "extra": len(frame["predictions"]) - len(matches),
            }
        )
        subsets = read_conditions(
            [r for r in rapid["rows"] if r["id"] == key], alternate
        )
        for name, predictions in subsets.items():
            conditions[name].append({"id": key, **score_image(truth[key], predictions)})
    write_json(
        args.output,
        {
            "protocol_sha256": digest(args.protocol),
            "scope": frozen["scope"],
            "raw_sha256": {
                str(p): digest(p) for p in (args.raw, args.rapid, args.trocr)
            },
            "crop_issues": [r for r in data["rows"] if r["issue"] is not None],
            "geometry": {
                "totals": {
                    name: sum(row[name] for row in geometry)
                    for name in (
                        "truth_lines",
                        "predictions",
                        "matched",
                        "missed",
                        "extra",
                    )
                },
                "rows": geometry,
            },
            "conditions": {
                name: {"totals": totals(rows), "rows": rows}
                for name, rows in conditions.items()
            },
        },
    )
    print(json.dumps({name: totals(rows) for name, rows in conditions.items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "detect", "rapid", "trocr", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--rapid", type=Path)
    parser.add_argument("--trocr", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Preserve all frozen outputs")
    try:
        {
            "freeze": freeze,
            "detect": detect,
            "rapid": read_rapid,
            "trocr": read_trocr,
            "score": score,
        }[args.mode](args)
    except BaseException as error:
        if args.mode != "freeze":
            write_json(
                args.output,
                {
                    "protocol_sha256": digest(args.protocol),
                    "complete": False,
                    "error": f"{type(error).__name__}: {error}",
                },
            )
        raise
