"""Fill only missing half-second proposals before the crowded birth control."""

import argparse
import json
import time
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_streaming import detector_boxes, source_frames, validate_cadence
from passage_entry_control import runtime_contract

ROOT = Path(__file__).parent
PROTOCOL = ROOT / "detection_birth_cache_protocol.json"
OUTPUT = Path(".cache/cow-cutie/birth-proposals.json")


def checked_inputs(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed frozen cache input: {filename}")
    clip = json.loads((Path(protocol["inputs"]["clip"]) / "sampled.json").read_text())
    validate_cadence(clip, protocol)
    baseline = json.loads(Path(protocol["inputs"]["baseline_predictions"]).read_text())
    if (
        not baseline["complete"]
        or baseline["provenance"]["protocol_sha256"]
        != protocol["baseline_protocol_sha256"]
    ):
        raise ValueError("The complete frozen six-seed baseline is required")
    if protocol["last_processed_second"] != 1529 or protocol["processing_fps"] != 2:
        raise ValueError("Cache fill is restricted to exposed0–1529at2fps")
    return protocol, clip, baseline


def execute(args):
    import torch
    from ultralytics import YOLO

    protocol, clip, baseline = checked_inputs(args.protocol)
    libraries = runtime_contract(protocol)
    if args.output.exists():
        raise FileExistsError("Preserve previous cached inference; do not reroll it")
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS required for the fixed half-second detector")
    torch.set_num_threads(2)
    model = YOLO(protocol["inputs"]["yolo_model"])
    original = {r["second"]: r for r in baseline["timeline"]}
    value = {
        "complete": False,
        "protocol_sha256": digest(args.protocol),
        "libraries": libraries,
        "timeline": [],
        "new_inference_seconds": [],
        "stop_reason": None,
    }
    capture = cv2.VideoCapture(str(Path(protocol["inputs"]["clip"]) / "sampled.avi"))
    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for index, (source, image) in enumerate(
                source_frames(capture, clip["rows"])
            ):
                if source["second"] in original:
                    old = original[source["second"]]
                    if (
                        old["source_pixels_sha256"] != source["pixels_sha256"]
                        or old["publisher_frame"] != source["publisher_frame"]
                    ):
                        raise ValueError(
                            "Reused proposals have different source pixels"
                        )
                    boxes, origin = old["raw_detector_boxes"], "frozen_integer_baseline"
                else:
                    tick = time.perf_counter()
                    boxes = detector_boxes(
                        model, image, protocol["corroborator"]["settings"]
                    )
                    torch.mps.synchronize()
                    value["new_inference_seconds"].append(time.perf_counter() - tick)
                    origin = "new_half_second"
                    if (
                        model.predictor.model.device.type != "mps"
                        or not model.predictor.model.fp16
                    ):
                        raise ValueError(
                            "Preserve the mixed detector FP16 MPS contract"
                        )
                value["timeline"].append(
                    {
                        "second": source["second"],
                        "publisher_frame": source["publisher_frame"],
                        "source_pixels_sha256": source["pixels_sha256"],
                        "boxes": boxes,
                        "origin": origin,
                    }
                )
                if index % 250 == 0:
                    print(
                        json.dumps(
                            {
                                "cached_frames": index + 1,
                                "new_inferences": len(value["new_inference_seconds"]),
                            }
                        ),
                        flush=True,
                    )
        value["complete"] = (
            len(value["timeline"]) == 3059
            and len(value["new_inference_seconds"]) == 1529
        )
        value["model_metadata"] = {
            "device": str(model.predictor.model.device),
            "fp16": model.predictor.model.fp16,
            "names": model.names,
        }
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        capture.release()
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    execute(parser.parse_args())
