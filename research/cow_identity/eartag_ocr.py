"""Frozen CPU OCR on public development tag crops; recognition is not cow identity."""

import argparse
import hashlib
import importlib.metadata
import json
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json

ROOT = Path(__file__).parent
DATA_PROTOCOL = ROOT / "eartag_dataset_protocol.json"
DATA_MANIFEST = Path(".cache/cow-eartag-inventory/manifest-v1.json")
ENGINE = Path(".cache/cow-ear-tags/ocr-engine.json")


def polygon(value):
    points = np.asarray(value, dtype=np.float32).reshape(-1, 2)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        return None
    if not cv2.isContourConvex(points) or cv2.contourArea(points) <= 0:
        return None
    return points


def polygon_iou(left, right):
    a, b = polygon(left), polygon(right)
    if a is None or b is None:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(a, b)
    return float(
        intersection / (cv2.contourArea(a) + cv2.contourArea(b) - intersection)
    )


def match_polygons(lines, predictions):
    from scipy.optimize import linear_sum_assignment

    if not lines or not predictions:
        return []
    overlap = np.array(
        [
            [
                polygon_iou(line["polygon"], prediction["polygon"])
                for prediction in predictions
            ]
            for line in lines
        ]
    )
    # Cardinality outranks any possible sum-IoU gain; text never affects pairing.
    weights = np.where(overlap >= 0.5, min(overlap.shape) + 1 + overlap, 0)
    left, right = linear_sum_assignment(weights, maximize=True)
    return [
        (int(i), int(j), float(overlap[i, j]))
        for i, j in zip(left, right, strict=True)
        if overlap[i, j] >= 0.5
    ]


def score_image(lines, predictions, minimum_score=None):
    chosen = [
        row
        for row in predictions
        if minimum_score is None or row["score"] >= minimum_score
    ]
    matches = match_polygons(lines, chosen)
    correct = sum(
        lines[i]["text"].strip() == chosen[j]["text"].strip() for i, j, _ in matches
    )
    return {
        "ground_truth_lines": len(lines),
        "predictions": len(chosen),
        "matched": len(matches),
        "correct_text": correct,
        "wrong_text": len(matches) - correct,
        "missed_lines": len(lines) - len(matches),
        "unmatched_texts": len(chosen) - len(matches),
        "full_tag_exact": correct == len(lines) == len(chosen),
        "matches": [
            {
                "truth_index": i,
                "prediction": chosen[j],
                "iou": overlap,
                "exact": lines[i]["text"].strip() == chosen[j]["text"].strip(),
            }
            for i, j, overlap in matches
        ],
        "invalid_truth_polygons": [
            i for i, row in enumerate(lines) if polygon(row["polygon"]) is None
        ],
        "invalid_prediction_polygons": [
            i for i, row in enumerate(chosen) if polygon(row["polygon"]) is None
        ],
        "nonstandard_truth_strings": [
            i
            for i, row in enumerate(lines)
            if not row["text"].strip() or "#" in row["text"]
        ],
    }


def freeze(args):
    import rapidocr

    dataset = json.loads(DATA_PROTOCOL.read_text())
    manifest = json.loads(DATA_MANIFEST.read_text())
    if digest(DATA_MANIFEST) != dataset["files"][str(DATA_MANIFEST)]:
        raise ValueError("Frozen dataset manifest changed")
    rows = {row["id"]: row for row in manifest["rows"]}
    selected = [rows[key] for key in dataset["pilot"]]
    if len(selected) != 64 or len({row["group"] for row in selected}) != 64:
        raise ValueError("Require the fixed64 distinct development groups")
    if any(row["split"] != "development" for row in selected):
        raise ValueError("No calibration, reserved or ambiguous-ID crops in this run")
    engine = json.loads(ENGINE.read_text())
    package = Path(rapidocr.__file__).parent
    models = {name: package / "models" / name for name in engine["models"]}
    if any(digest(path) != engine["models"][name] for name, path in models.items()):
        raise ValueError("Bundled OCR weights changed")
    config = package / "config.yaml"
    if digest(config) != engine["config_sha256"]:
        raise ValueError("Bundled OCR defaults changed")
    params = {
        **engine["params"],
        "Det.model_path": str(models["PP-OCRv6_det_small.onnx"]),
        "Cls.model_path": str(models["ch_ppocr_mobile_v2.0_cls_mobile.onnx"]),
        "Rec.model_path": str(models["PP-OCRv6_rec_small.onnx"]),
    }
    libraries = {
        name: importlib.metadata.version(name)
        for name in (*engine["libraries"], "scipy")
    }
    files = [
        Path(__file__),
        ROOT / "test_eartag_ocr.py",
        ROOT / "benchmark.py",
        ROOT / "scoring.py",
        DATA_PROTOCOL,
        DATA_MANIFEST,
        ENGINE,
        config,
        *models.values(),
        *sorted(package.rglob("*.py")),
        *(Path(row["image"]) for row in selected),
    ]
    write_json(
        args.protocol,
        {
            "scope": "First64 frozen development groups from preselected grayscale ear-tag crops. CPU OCR only, no tag localization/full-animal association or automatic cow-ID claim. No calibration/reserved/ambiguous crops.",
            "files": {str(path): digest(path) for path in files},
            "libraries": libraries,
            "params": params,
            "cv_threads": 2,
            "disable_onnx_telemetry": True,
            "expected_providers": ["CPUExecutionProvider"],
            "raw_input": [
                {
                    key: row[key]
                    for key in ("id", "image", "image_sha256", "pixels_sha256")
                }
                for row in selected
            ],
            "score": {
                "minimum_polygon_iou": 0.5,
                "minimum_accepted_score": 0.95,
                "matching": "Geometry only; unique global assignment maximizes(min(nGT,nPred)+1+IoU) on edgesIoU>=.5. This gives cardinality first then totalIoU. Invalid polygons remain unmatched and are explicitly counted.",
                "text": "Only strip outside whitespace; preserve zeros/punctuation/case/all lines. No roster, character allowlist, annotation cropping, label-order requirement or normalization.",
                "counts": "All GTlines in denominator, wrong matched transcripts plus unmatched accepted texts are false positives. Fulltag exact requires everyGTline exact and no extras.",
            },
            "raw_cache": "Key binds source JPEG/pixel hashes, engine versions/config/weights/source and all effective parameters. Cache contains rawquad/text/score only; no truth or inferred cowID.",
        },
    )


def checked(path):
    frozen = json.loads(path.read_text())
    for name, expected in frozen["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen OCR input changed: {name}")
    if {
        name: importlib.metadata.version(name) for name in frozen["libraries"]
    } != frozen["libraries"]:
        raise ValueError("OCR/scorer libraries changed")
    return frozen


def read_image(source):
    content = Path(source["image"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != source["image_sha256"]:
        raise ValueError("Fixed source JPEG changed")
    encoded = np.frombuffer(content, np.uint8)
    gray = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if (
        gray is None
        or hashlib.sha256(str(gray.shape).encode() + gray.tobytes()).hexdigest()
        != source["pixels_sha256"]
    ):
        raise ValueError("Source pixels differ from inventory")
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return image, hashlib.sha256(
        str(image.shape).encode() + image.tobytes()
    ).hexdigest()


def read_predictions(engine, image):
    output = engine(image)
    if output.boxes is None and output.txts is None and output.scores is None:
        return []
    if any(value is None for value in (output.boxes, output.txts, output.scores)):
        raise ValueError("Partial OCR output is not a successful empty result")
    predictions = []
    for bounds, text, score in zip(
        output.boxes, output.txts, output.scores, strict=True
    ):
        if not np.isfinite(score) or not np.isfinite(bounds).all():
            raise ValueError("Nonfinite OCR output")
        predictions.append(
            {"polygon": bounds.tolist(), "text": text, "score": float(score)}
        )
    return predictions


def infer(args):
    import onnxruntime
    from rapidocr import RapidOCR

    frozen = checked(args.protocol)
    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(frozen["cv_threads"])
    started = time.perf_counter()
    engine = RapidOCR(params=frozen["params"])
    providers = {
        key: getattr(engine, key).session.session.get_providers()
        for key in ("text_det", "text_cls", "text_rec")
    }
    if any(value != frozen["expected_providers"] for value in providers.values()):
        raise ValueError("This experiment requires actual CPU-only OCR sessions")
    report = {
        "protocol_sha256": digest(args.protocol),
        "complete": False,
        "initialization_seconds": time.perf_counter() - started,
        "providers": providers,
        "rows": [],
        "error": None,
    }
    cache = Path(".cache/cow-ear-tags/raw")
    cache.mkdir(parents=True, exist_ok=True)
    try:
        for source in frozen["raw_input"]:
            tick = time.perf_counter()
            image, actual_pixels_sha256 = read_image(source)
            key = hashlib.sha256(
                json.dumps(
                    [report["protocol_sha256"], source, actual_pixels_sha256],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            path = cache / (key + ".json")
            reused = path.exists()
            if reused:
                result = json.loads(path.read_text())
                if result["cache_key"] != key:
                    raise ValueError("OCR cache key mismatch")
            else:
                result = {
                    "cache_key": key,
                    "predictions": read_predictions(engine, image),
                    "inference_bgr_pixels_sha256": actual_pixels_sha256,
                }
                write_json(path, result)
            report["rows"].append(
                {
                    **source,
                    **result,
                    "cache_hit": reused,
                    "seconds": time.perf_counter() - tick,
                }
            )
        report["complete"] = len(report["rows"]) == 64
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, report)
        print(
            json.dumps({key: value for key, value in report.items() if key != "rows"}),
            flush=True,
        )


def totals(rows):
    fields = (
        "ground_truth_lines",
        "predictions",
        "matched",
        "correct_text",
        "wrong_text",
        "missed_lines",
        "unmatched_texts",
        "full_tag_exact",
    )
    result = {field: sum(row[field] for row in rows) for field in fields}
    result.update(
        exact_line_coverage=result["correct_text"] / result["ground_truth_lines"]
        if result["ground_truth_lines"]
        else None,
        exact_text_precision=result["correct_text"] / result["predictions"]
        if result["predictions"]
        else None,
        full_tag_accuracy=result["full_tag_exact"] / len(rows),
    )
    return result


def score(args):
    frozen = checked(args.protocol)
    raw = json.loads(args.raw.read_text())
    if (
        not raw["complete"]
        or raw["protocol_sha256"] != digest(args.protocol)
        or [
            {key: row[key] for key in ("id", "image", "image_sha256", "pixels_sha256")}
            for row in raw["rows"]
        ]
        != frozen["raw_input"]
    ):
        raise ValueError("Only complete exact raw64 output can be scored")
    # Annotation data is loaded for the first time AFTER immutable raw OCR completes.
    truth = {
        row["id"]: row["lines"] for row in json.loads(DATA_MANIFEST.read_text())["rows"]
    }
    conditions = {}
    for label, threshold in (
        ("all_raw", None),
        ("accepted_0.95", frozen["score"]["minimum_accepted_score"]),
    ):
        rows = [
            {
                "id": row["id"],
                **score_image(truth[row["id"]], row["predictions"], threshold),
            }
            for row in raw["rows"]
        ]
        conditions[label] = {"totals": totals(rows), "rows": rows}
    result = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.protocol),
        "raw_sha256": digest(args.raw),
        "conditions": conditions,
        "cpu_seconds": {
            "initialization": raw["initialization_seconds"],
            "total": raw["elapsed_seconds"],
            "per_image_p50_p95_max": np.quantile(
                [r["seconds"] for r in raw["rows"]], [0.5, 0.95, 1]
            ).tolist(),
            "cache_hits": sum(r["cache_hit"] for r in raw["rows"]),
        },
        "annotation_issues": dict(
            Counter(
                issue
                for r in conditions["all_raw"]["rows"]
                for issue in ("invalid_truth_polygons", "nonstandard_truth_strings")
                if r[issue]
            )
        ),
    }
    write_json(args.output, result)
    print(json.dumps({key: row["totals"] for key, row in conditions.items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "infer", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve frozen protocols")
        freeze(args)
    else:
        if args.output is None or args.output.exists():
            parser.error("Pass a new output path")
        if args.mode == "score" and args.raw is None:
            parser.error("Scoring requires completed raw predictions")
        (infer if args.mode == "infer" else score)(args)
