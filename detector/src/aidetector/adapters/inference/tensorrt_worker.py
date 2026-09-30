"""Short-lived SDK export and GPU smoke test; the parent publishes the engine."""

import json
import logging
import os
import sys
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)


def exit_with_parent() -> None:
    # The parent keeps this pipe open. A crash/forced shutdown must not leave
    # an engine builder running after the monitoring process has gone away.
    sys.stdin.buffer.read()
    os._exit(1)


def build_and_test(request: dict) -> None:
    import numpy as np
    from ultralytics import YOLO

    from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
    from aidetector.configuration import OnnxConfig

    arguments = request["export"]
    checkpoint = request["checkpoint"]
    requirements = (
        ModelRequirements(checkpoint, arguments["imgsz"], arguments["batch"]),
    )
    with inference_runtime(OnnxConfig(), requirements, "cuda"):
        model = YOLO(checkpoint, task=request["task"])
        exported = model.export(**arguments)
        del model
        model = YOLO(str(exported), task=request["task"])
        size = arguments["imgsz"]
        for count in sorted({1, arguments["batch"]}):
            for height in sorted({size, max(32, size // 2 // 32 * 32)}):
                images = [
                    np.zeros((height, size, 3), dtype=np.uint8) for _ in range(count)
                ]
                results = model.predict(
                    images, device=0, imgsz=size, batch=count, rect=True, verbose=False
                )
                if len(results) != count or any(
                    result.boxes is None
                    or not np.isfinite(result.boxes.cpu().numpy().data).all()
                    for result in results
                ):
                    raise RuntimeError(
                        "TensorRT GPU smoke test produced invalid detection results"
                    )
        logger.info(
            "TensorRT GPU smoke test passed (batch 1..%d, square and rectangular inputs)",
            arguments["batch"],
        )


def run_helper(request_path: Path) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    Thread(target=exit_with_parent, daemon=True, name="parent-control").start()
    try:
        build_and_test(json.loads(request_path.read_text(encoding="utf-8")))
        return 0
    except Exception:
        logger.exception("TensorRT preparation failed")
        return 1
