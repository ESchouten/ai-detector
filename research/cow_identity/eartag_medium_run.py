"""Convert frozen JSON model-type strings at RapidOCR's public enum boundary."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
from benchmark import digest, write_json
from eartag_ocr import checked, read_image, read_predictions


def freeze(args):
    original = Path(__file__).with_name("eartag_medium_control_protocol.json")
    frozen = checked(original)
    frozen["files"].update(
        {__file__: digest(Path(__file__)), str(original): digest(original)}
    )
    frozen["serialization_correction"] = {
        "failed_protocol_sha256": digest(original),
        "reason": "First launch failed before model construction: RapidOCR public params require ModelType enum, not JSON string. This adapter converts only the two frozen small/medium metadata values to their SDK enum; weights, pipeline, inputs, thresholds and scoring unchanged.",
        "initial_cattle_outputs": 0,
    }
    write_json(args.protocol, frozen)


def infer(args):
    import onnxruntime
    from rapidocr import ModelType, RapidOCR

    frozen = checked(args.protocol)
    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(frozen["cv_threads"])
    params = dict(frozen["params"])
    for component in ("Det", "Rec"):
        params[f"{component}.model_type"] = ModelType(params[f"{component}.model_type"])
    start = time.perf_counter()
    engine = RapidOCR(params=params)
    providers = {
        key: getattr(engine, key).session.session.get_providers()
        for key in ("text_det", "text_cls", "text_rec")
    }
    if any(value != frozen["expected_providers"] for value in providers.values()):
        raise ValueError("CPU-only OCR required")
    report = {
        "protocol_sha256": digest(args.protocol),
        "complete": False,
        "initialization_seconds": time.perf_counter() - start,
        "providers": providers,
        "rows": [],
        "error": None,
    }
    cache = Path(".cache/cow-ear-tags/raw")
    cache.mkdir(parents=True, exist_ok=True)
    try:
        for source in frozen["raw_input"]:
            tick = time.perf_counter()
            image, pixel_hash = read_image(source)
            key = hashlib.sha256(
                json.dumps(
                    [report["protocol_sha256"], source, pixel_hash], sort_keys=True
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
                    "inference_bgr_pixels_sha256": pixel_hash,
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
        report["elapsed_seconds"] = time.perf_counter() - start
        write_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "infer"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.protocol if args.mode == "freeze" else args.output
    if destination is None or destination.exists():
        parser.error("Use a new output path")
    (freeze if args.mode == "freeze" else infer)(args)
