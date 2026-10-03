"""Extend frozen detector evidence to exposed second2999, without rerolling rows."""

import argparse
import json
import time
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_streaming import detector_boxes, source_frames, validate_cadence
from passage_entry_control import runtime_contract


def join_existing(prefix, integers, sources):
    """Require exact overlap and source correspondence before choosing cache rows."""
    expected = {row["second"]: row for row in sources}
    if len(expected) != len(sources):
        raise ValueError("Duplicate source timestamps")
    combined = {}
    for origin, rows in (
        ("frozen_development_cache", prefix),
        ("frozen_reserved_integer", integers),
    ):
        seen = set()
        for row in rows:
            second = row["second"]
            if second in seen or second not in expected:
                raise ValueError("Duplicate or out-of-scope cached timestamp")
            seen.add(second)
            source = expected[second]
            if (
                row["publisher_frame"] != source["publisher_frame"]
                or row["source_pixels_sha256"] != source["pixels_sha256"]
            ):
                raise ValueError("Cached proposals have different source pixels")
            boxes = row["boxes"] if "boxes" in row else row["raw_detector_boxes"]
            # The old streaming rows also have propagated boxes: use raw evidence.
            if origin == "frozen_reserved_integer":
                boxes = row["raw_detector_boxes"]
            if second in combined and combined[second]["boxes"] != boxes:
                raise ValueError("Overlapping detector arrays differ")
            combined.setdefault(second, {"boxes": boxes, "origin": origin})
    return combined


def checked_inputs(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed frozen cache input: {filename}")
    if protocol["last_processed_second"] != 2999 or protocol["processing_fps"] != 2:
        raise ValueError("Only the already exposed0–2999extension is authorized")
    clip = json.loads((Path(protocol["inputs"]["clip"]) / "sampled.json").read_text())
    validate_cadence(clip, protocol)
    prefix = json.loads(Path(protocol["inputs"]["prefix_cache"]).read_text())
    old = json.loads(Path(protocol["inputs"]["integer_run"]).read_text())
    if (
        not prefix["complete"]
        or not old["complete"]
        or prefix["protocol_sha256"] != protocol["prefix_protocol_sha256"]
        or old["provenance"]["protocol_sha256"] != protocol["integer_protocol_sha256"]
        or prefix["libraries"] != protocol["libraries"]
        or old["provenance"]["libraries"] != protocol["libraries"]
        or prefix["model_metadata"] != protocol["detector_metadata"]
        or old["model_metadata"] != protocol["integer_model_metadata"]
    ):
        raise ValueError("Reused detector provenance changed")
    if [r["second"] for r in prefix["timeline"]] != [i / 2 for i in range(3059)] or [
        r["second"] for r in old["timeline"]
    ] != list(range(3000)):
        raise ValueError("Both complete original caches are required")
    combined = join_existing(prefix["timeline"], old["timeline"], clip["rows"])
    missing = [r["second"] for r in clip["rows"] if r["second"] not in combined]
    if len(combined) != 4529 or missing != [1529.5 + i for i in range(1470)]:
        raise ValueError("Only1470newhalfseconds may receive inference")
    return protocol, clip, combined


def execute(args):
    import torch
    from ultralytics import YOLO

    protocol, clip, previous = checked_inputs(args.protocol)
    libraries = runtime_contract(protocol)
    if args.output.exists():
        raise FileExistsError("Preserve prior inference; do not reroll cache rows")
    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual MPS required for this frozen detector extension")
    torch.set_num_threads(2)
    model = YOLO(protocol["inputs"]["yolo_model"])
    value = {
        "complete": False,
        "protocol_sha256": digest(args.protocol),
        "libraries": libraries,
        "timeline": [],
        "new_inference_seconds": [],
        "stop_reason": None,
        "reused_rows": len(previous),
    }
    capture = cv2.VideoCapture(str(Path(protocol["inputs"]["clip"]) / "sampled.avi"))
    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for index, (source, image) in enumerate(
                source_frames(capture, clip["rows"])
            ):
                cached = previous.get(source["second"])
                if cached is None:
                    tick = time.perf_counter()
                    boxes = detector_boxes(
                        model, image, protocol["corroborator"]["settings"]
                    )
                    torch.mps.synchronize()
                    value["new_inference_seconds"].append(time.perf_counter() - tick)
                    if (
                        model.predictor.model.device.type != "mps"
                        or not model.predictor.model.fp16
                    ):
                        raise ValueError("Preserve the FP16 MPS detector contract")
                    cached = {"boxes": boxes, "origin": "new_extended_half_second"}
                value["timeline"].append(
                    {
                        "second": source["second"],
                        "publisher_frame": source["publisher_frame"],
                        "source_pixels_sha256": source["pixels_sha256"],
                        **cached,
                    }
                )
                if index % 500 == 0:
                    print(
                        json.dumps(
                            {
                                "rows": index + 1,
                                "new_calls": len(value["new_inference_seconds"]),
                            }
                        ),
                        flush=True,
                    )
        value["model_metadata"] = {
            "device": str(model.predictor.model.device),
            "fp16": model.predictor.model.fp16,
            "names": {str(k): v for k, v in model.names.items()},
        }
        if value["model_metadata"] != protocol["detector_metadata"]:
            raise ValueError("Final detector metadata differs from reused inference")
        value["complete"] = (
            len(value["timeline"]) == 5999
            and len(value["new_inference_seconds"]) == 1470
        )
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        capture.release()
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    execute(parser.parse_args())
