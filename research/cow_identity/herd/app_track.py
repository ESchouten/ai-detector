"""Detect and track the cows of one video with the application's detector adapter.

The boxes do not depend on who is enrolled, so they are computed once per video
and reused whenever a different herd model is tried on it.
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from app_run import SOURCE, detector_config, digest
from ethz import VIDEOS

from aidetector.adapters.inference.identity_observations import infrared
from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.inference.yolo import open_detector
from aidetector.adapters.media.images import shrink_image
from aidetector.configuration import Config
from aidetector.domain.models import Frame
from aidetector.version import TYPE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, choices=sorted(VIDEOS))
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--detector-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    # The herd weights play no part here, so the preset's own address stays.
    config = Config.model_validate(
        {"detectors": [detector_config(arguments.preset, arguments.detector_weights)]}
    )
    settings = config.detectors[0]
    index = json.loads((arguments.frames / "frames.json").read_text())
    start = datetime.fromisoformat(VIDEOS[arguments.video]["start"])
    boxes, seconds = [], []
    models = (ModelRequirements(settings.yolo.model, settings.yolo.imgsz, 1),)
    with (
        inference_runtime(config.onnx, models, TYPE) as options,
        open_detector(settings.yolo, config.onnx, (SOURCE,), TYPE, options) as detector,
    ):
        for step, sampled in enumerate(index["frames"]):
            original = cv2.imread(str(arguments.frames / sampled["file"]))
            image = shrink_image(original, settings.detection.frames_width)
            scale = original.shape[1] / image.shape[1]
            frame = Frame(start + timedelta(seconds=step), image)
            started = time.perf_counter()
            observation = detector.detect({SOURCE: (frame,)})[SOURCE][-1]
            seconds.append(time.perf_counter() - started)
            for box in observation.boxes:
                boxes.append(
                    {
                        "index": sampled["index"],
                        "file": sampled["file"],
                        "seconds": float(step),
                        "app_box": [box.x1, box.y1, box.x2, box.y2],
                        "app_size": [image.shape[1], image.shape[0]],
                        "box": [value * scale for value in (box.x1, box.y1, box.x2, box.y2)],
                        "frame_size": [original.shape[1], original.shape[0]],
                        "infrared": infrared(image),
                        "track": box.track_id,
                        "confidence": box.confidence,
                    }
                )
    warm = np.array(seconds[10:])
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(
            {
                "video": arguments.video,
                "frames": len(index["frames"]),
                "preset": json.loads(arguments.preset.read_text()),
                "detector_weights_sha256": digest(arguments.detector_weights),
                "detect_seconds": {
                    "mean": float(warm.mean()),
                    "p95": float(np.quantile(warm, 0.95)),
                    "max": float(warm.max()),
                },
                "boxes": boxes,
            }
        )
        + "\n"
    )
    print(f"{arguments.video}: {len(boxes)} boxes, {warm.mean() * 1000:.0f} ms/frame")


if __name__ == "__main__":
    main()
