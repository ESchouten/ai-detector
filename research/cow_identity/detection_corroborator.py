"""Cache stateless cow detections for a frozen hybrid identity experiment."""

import argparse
import json
import time
from pathlib import Path

import cv2
from benchmark import digest, write_json
from video_assessment import detector_libraries, pixels_hash


def run(args, protocol, clip):
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(2)
    model = YOLO(str(args.model))
    result = {
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "runner_sha256": digest(Path(__file__)),
            "model_sha256": digest(args.model),
            "sampled_manifest_sha256": digest(args.clip / "sampled.json"),
            "video_sha256": clip["contract"]["video_sha256"],
            "settings": protocol["corroborator"]["settings"],
            "libraries": detector_libraries(),
        },
        "complete": False,
        "class_names": model.names,
        "timeline": [],
    }
    capture = cv2.VideoCapture(str(args.clip / "sampled.avi"))
    started = time.perf_counter()
    try:
        for source in clip["rows"]:
            ok, image = capture.read()
            if not ok:
                raise ValueError("Corroborator source ended before its frozen manifest")
            if not float(source["second"]).is_integer():
                continue
            if pixels_hash(image) != source["pixels_sha256"]:
                raise ValueError("Corroborator pixels differ from frozen source")
            tick = time.perf_counter()
            prediction = model.predict(
                image, verbose=False, **protocol["corroborator"]["settings"]
            )[0]
            boxes = [
                {
                    **dict(
                        zip(("x1", "y1", "x2", "y2"), map(int, bounds), strict=True)
                    ),
                    "confidence": confidence,
                }
                for bounds, confidence in zip(
                    prediction.boxes.xyxy.cpu().tolist(),
                    prediction.boxes.conf.cpu().tolist(),
                    strict=True,
                )
            ]
            second = int(source["second"])
            result["timeline"].append(
                {
                    "second": second,
                    "source_pixels_sha256": source["pixels_sha256"],
                    "publisher_frame": source["publisher_frame"],
                    "boxes": boxes,
                    "inference_seconds": time.perf_counter() - tick,
                }
            )
            if second % 100 == 0:
                write_json(args.output, result)
                print(json.dumps({"second": second, "boxes": len(boxes)}), flush=True)
        if [row["second"] for row in result["timeline"]] != list(
            range(protocol["last_processed_second"] + 1)
        ):
            raise ValueError("Corroboration requires every frozen integer-second frame")
        result.update(
            complete=True,
            elapsed_seconds=time.perf_counter() - started,
            actual_device=str(model.predictor.model.device),
            actual_fp16=model.predictor.model.fp16,
            resolved_preprocessing={
                key: vars(model.predictor.args)[key]
                for key in (
                    "imgsz",
                    "rect",
                    "batch",
                    "quantize",
                    "conf",
                    "iou",
                    "max_det",
                )
            },
        )
        write_json(args.output, result)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("clip", "model", "protocol", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    if digest(Path(__file__)) != protocol["corroborator"]["runner_sha256"]:
        parser.error("Corroborator runner differs from the frozen implementation")
    if args.output.exists():
        parser.error("Preserve existing predictions; choose a fresh output file")
    for path, expected in (
        (args.model, protocol["corroborator"]["model_sha256"]),
        (args.clip / "sampled.json", protocol["sampled_manifest_sha256"]),
        (args.clip / "sampled.avi", protocol["sampled_clip_sha256"]),
    ):
        if digest(path) != expected:
            parser.error(f"Changed frozen corroborator input: {path}")
    clip = json.loads((args.clip / "sampled.json").read_text())
    expected = [
        index / protocol["processing_fps"]
        for index in range(
            protocol["last_processed_second"] * protocol["processing_fps"] + 1
        )
    ]
    if [row["second"] for row in clip["rows"]] != expected:
        parser.error("Source frame cadence changed")
    run(args, protocol, clip)


if __name__ == "__main__":
    main()
