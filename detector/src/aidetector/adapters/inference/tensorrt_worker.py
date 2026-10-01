"""Short-lived SDK export and GPU smoke test; the parent publishes the engine."""

import faulthandler
import json
import logging
import os
import sys
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)
TRACE_INTERVAL = 60.0


def exit_with_parent() -> None:
    # The parent keeps this pipe open. A crash/forced shutdown must not leave
    # an engine builder running after the monitoring process has gone away.
    # A buffered read holds Python's stdin lock and can abort interpreter
    # shutdown when a completed helper exits with this daemon still waiting.
    while os.read(sys.stdin.fileno(), 1):
        pass
    os._exit(1)


def build_and_test(request: dict) -> None:
    logger.info("TensorRT preparation: importing inference libraries")
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
        logger.info("TensorRT preparation: loading checkpoint %s", checkpoint)
        model = YOLO(checkpoint, task=request["task"])
        logger.info(
            "TensorRT preparation: exporting and building engine; settings=%s",
            arguments,
        )
        exported = model.export(**arguments)
        logger.info(
            "TensorRT preparation: engine export complete; loading GPU test model"
        )
        del model
        model = YOLO(str(exported), task=request["task"])
        size = arguments["imgsz"]
        for count in sorted({1, arguments["batch"]}):
            for height in sorted({size, max(32, size // 2 // 32 * 32)}):
                logger.info(
                    "TensorRT GPU test: batch=%d; image=%dx%d", count, height, size
                )
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
    # Enable diagnostics before importing inference libraries: a native import
    # can hang without ever raising a Python exception.
    faulthandler.enable()
    faulthandler.dump_traceback_later(TRACE_INTERVAL, repeat=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    Thread(target=exit_with_parent, daemon=True, name="parent-control").start()
    try:
        logger.info("TensorRT helper started; pid=%d", os.getpid())
        logger.info(
            "Python thread stacks are recorded every %.0fs while preparation runs; a snapshot alone does not indicate a failure",
            TRACE_INTERVAL,
        )
        build_and_test(json.loads(request_path.read_text(encoding="utf-8")))
        return 0
    except Exception:
        logger.exception("TensorRT preparation failed")
        return 1
    finally:
        faulthandler.cancel_dump_traceback_later()
