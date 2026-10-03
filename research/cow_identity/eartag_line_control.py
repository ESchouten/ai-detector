"""Development-only oracle line polygons isolate localization from OCR reading."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, checked, polygon, read_image

BASE = Path(__file__).with_name("eartag_ocr_protocol.json")


def inputs_without_text(manifest, sources):
    by_id = {row["id"]: row for row in manifest["rows"]}
    return [
        {
            **source,
            "lines": [
                {"index": index, "polygon": line["polygon"]}
                for index, line in enumerate(by_id[source["id"]]["lines"])
            ],
        }
        for source in sources
    ]


def freeze(args):
    base = checked(BASE)
    sources = inputs_without_text(
        json.loads(DATA_MANIFEST.read_text()), base["raw_input"]
    )
    if sum(len(row["lines"]) for row in sources) != 157:
        raise ValueError("Require all 157 original development lines")
    files = {
        **base["files"],
        str(BASE): digest(BASE),
        __file__: digest(Path(__file__)),
        str(Path(__file__).with_name("test_eartag_line_control.py")): digest(
            Path(__file__).with_name("test_eartag_line_control.py")
        ),
    }
    write_json(
        args.protocol,
        {
            "scope": "Oracle localization diagnostic on the same fixed64 development tags and all157 publisher text polygons. Not an automatic detector or cow-ID result. No calibration/reserved images.",
            "files": files,
            "libraries": base["libraries"],
            "params": base["params"],
            "raw_input": sources,
            "recipe": "Original verified BGR pixels; publisher four-corner order unchanged; pinned RapidOCR get_rotate_crop_image (cubic perspective warp, replicated border, SDK tall-crop rotation), then the same SDK cls_and_rotate and recognize_txt. No text detector call, extra padding, custom sharpening, character constraints, label text, roster or orientation search. One crop per line, raw score retained. Invalid polygon is explicit missing result, not removed.",
            "score": "Original literal strip-only exact match, all157 lines retained. Fixed raw and score>=.95 conditions; fulltag requires every original line correct. Recognition sees no transcript; scoring loads transcripts only after all157 outputs saved. This oracle cannot produce detector extras, so precision is conditional on perfect line proposals, not directly a pipeline guarantee.",
            "expected_providers": ["CPUExecutionProvider"],
            "cv_threads": 2,
        },
    )


def recognize_line(engine, image, points):
    from rapidocr.utils.process_img import get_rotate_crop_image

    shape = polygon(points)
    if shape is None:
        return {"text": None, "score": None, "issue": "invalid polygon"}
    crop = get_rotate_crop_image(image, shape.copy())
    pixel_hash = hashlib.sha256(str(crop.shape).encode() + crop.tobytes()).hexdigest()
    rotated, _ = engine.cls_and_rotate([crop])
    result = engine.recognize_txt(rotated)
    if result.txts is None or result.scores is None or len(result.txts) != 1:
        raise ValueError("Expected exactly one raw transcript per supplied line")
    return {
        "text": str(result.txts[0]),
        "score": float(result.scores[0]),
        "issue": None,
        "crop_shape": list(crop.shape),
        "crop_pixels_sha256": pixel_hash,
    }


def infer(args):
    import onnxruntime
    from rapidocr import RapidOCR

    frozen = checked(args.protocol)
    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(frozen["cv_threads"])
    start = time.perf_counter()
    engine = RapidOCR(params=frozen["params"])
    providers = {
        name: getattr(engine, name).session.session.get_providers()
        for name in ("text_cls", "text_rec")
    }
    if any(value != frozen["expected_providers"] for value in providers.values()):
        raise ValueError("CPU-only control required")
    report = {
        "protocol_sha256": digest(args.protocol),
        "complete": False,
        "providers": providers,
        "initialization_seconds": time.perf_counter() - start,
        "rows": [],
        "error": None,
    }
    try:
        for source in frozen["raw_input"]:
            image, actual_hash = read_image(source)
            for line in source["lines"]:
                tick = time.perf_counter()
                report["rows"].append(
                    {
                        "id": source["id"],
                        "index": line["index"],
                        "polygon": line["polygon"],
                        "inference_bgr_pixels_sha256": actual_hash,
                        **recognize_line(engine, image, line["polygon"]),
                        "seconds": time.perf_counter() - tick,
                    }
                )
        report["complete"] = len(report["rows"]) == 157
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - start
        write_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


def line_totals(truth, rows, threshold):
    accepted = [
        row
        for row in rows
        if row["text"] is not None and (threshold is None or row["score"] >= threshold)
    ]
    correct = {
        (row["id"], row["index"])
        for row in accepted
        if row["text"].strip() == truth[row["id"]][row["index"]]["text"].strip()
    }
    tags = {row["id"] for row in rows}
    return {
        "ground_truth_lines": len(rows),
        "accepted": len(accepted),
        "correct_text": len(correct),
        "wrong_text": len(accepted) - len(correct),
        "missed_or_rejected": len(rows) - len(accepted),
        "full_tag_exact": sum(
            all((key, index) in correct for index in range(len(truth[key])))
            for key in tags
        ),
        "tags": len(tags),
        "exact_line_coverage": len(correct) / len(rows),
        "accepted_exact_precision": len(correct) / len(accepted) if accepted else None,
    }


def score(args):
    frozen = checked(args.protocol)
    raw = json.loads(args.raw.read_text())
    expected = [
        (source["id"], line["index"], line["polygon"])
        for source in frozen["raw_input"]
        for line in source["lines"]
    ]
    if (
        not raw["complete"]
        or raw["error"] is not None
        or raw["protocol_sha256"] != digest(args.protocol)
        or [(r["id"], r["index"], r["polygon"]) for r in raw["rows"]] != expected
    ):
        raise ValueError("Only complete exact157 raw outputs can be scored")
    truth = {
        row["id"]: row["lines"] for row in json.loads(DATA_MANIFEST.read_text())["rows"]
    }
    result = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.protocol),
        "raw_sha256": digest(args.raw),
        "conditions": {
            label: line_totals(truth, raw["rows"], threshold)
            for label, threshold in (("all_raw", None), ("accepted_0.95", 0.95))
        },
        "cpu_seconds": {
            "initialization": raw["initialization_seconds"],
            "total": raw["elapsed_seconds"],
            "per_line_p50_p95_max": np.quantile(
                [r["seconds"] for r in raw["rows"]], [0.5, 0.95, 1]
            ).tolist(),
        },
    }
    write_json(args.output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "infer", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args()
    destination = args.protocol if args.mode == "freeze" else args.output
    if destination is None or destination.exists():
        parser.error("Use a new destination; frozen outputs are immutable")
    {"freeze": freeze, "infer": infer, "score": score}[args.mode](args)
