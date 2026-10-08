"""Run a detector and its tracker over sampled frames and keep every box.

The output is the input of every later stage, so a detector or tracker change
never requires decoding the video again, and an identification change never
requires running the detector again.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path, help="Folder written by sample_frames")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="cow")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--size", type=int, default=640)
    parser.add_argument("--tracker", default="bytetrack.yaml")
    parser.add_argument("--device", default="mps")
    arguments = parser.parse_args()

    index = json.loads((arguments.frames / "frames.json").read_text())
    model = YOLO(str(arguments.weights))
    classes = [key for key, name in model.names.items() if name == arguments.label]
    if not classes:
        raise SystemExit(f"{arguments.weights.name} has no class {arguments.label!r}")
    rows = []
    seconds = []
    for frame in index["frames"]:
        image = cv2.imread(str(arguments.frames / frame["file"]))
        started = time.perf_counter()
        result = model.track(
            image,
            persist=True,
            tracker=arguments.tracker,
            conf=arguments.confidence,
            classes=classes,
            imgsz=arguments.size,
            device=arguments.device,
            half=False,
            verbose=False,
        )[0]
        seconds.append(time.perf_counter() - started)
        boxes = result.boxes
        tracks = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
        rows.append(
            {
                "index": frame["index"],
                "seconds": frame["seconds"],
                "boxes": [
                    {
                        "box": [round(value, 1) for value in box],
                        "confidence": round(confidence, 4),
                        "track": track,
                    }
                    for box, confidence, track in zip(
                        boxes.xyxy.tolist(), boxes.conf.tolist(), tracks, strict=True
                    )
                ],
            }
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    warm = sorted(seconds[10:])
    arguments.output.write_text(
        json.dumps(
            {
                "video": index["video"],
                "weights": arguments.weights.name,
                "weights_sha256": hashlib.file_digest(
                    arguments.weights.open("rb"), "sha256"
                ).hexdigest(),
                "confidence": arguments.confidence,
                "size": arguments.size,
                "tracker": arguments.tracker,
                "device": arguments.device,
                "frame_seconds": {
                    "mean": sum(warm) / len(warm),
                    "p95": warm[int(len(warm) * 0.95)],
                    "max": warm[-1],
                },
                "frames": rows,
            }
        )
        + "\n"
    )
    print(arguments.output, len(rows), "frames", f"{sum(warm) / len(warm) * 1000:.1f} ms/frame")


if __name__ == "__main__":
    main()
