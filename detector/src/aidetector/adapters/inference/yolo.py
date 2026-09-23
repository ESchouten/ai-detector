from __future__ import annotations

import logging
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from ultralytics import YOLO
from ultralytics.data.loaders import LoadStreams, SourceTypes
from ultralytics.engine.results import Results

from aidetector.adapters.inference.model_assets import MODEL_DOWNLOAD_HELP
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.ports import Frames
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import OnnxConfig, YoloConfig
from aidetector.domain.models import BoundingBox, Frame, Observation

logger = logging.getLogger(__name__)


class InMemoryStreamBatch(LoadStreams):
    """Ultralytics loader adapter that gives every tracker a stable source slot."""

    def __init__(self, paths: list[str], images: list[NDArray[np.uint8]]):
        self.sources = paths
        self.images = images
        self.bs = len(images)
        self.mode = "stream"
        self.source_type = SourceTypes(stream=True)
        self.count = 0

    def __iter__(self):
        self.count = 0
        return self

    def __next__(self):
        if self.count:
            raise StopIteration
        self.count += 1
        return self.sources, self.images, [""] * self.bs

    def __len__(self) -> int:
        return self.bs

    def close(self) -> None:
        # The batch borrows arrays; it owns no video captures or threads.
        pass


def map_observations(
    result: Results, frames: tuple[Frame, ...], classes: dict[int, tuple[str, float]]
) -> tuple[Observation, ...]:
    boxes: list[BoundingBox] = []
    confidences: dict[str, float] = {}
    if result.boxes is not None:
        for box in result.boxes:
            class_id = int(box.cls.item())
            configured = classes.get(class_id)
            if configured is None:
                continue
            name, threshold = configured
            score = float(box.conf.item())
            if score < threshold:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            track_id = int(box.id.item()) if box.id is not None else None
            boxes.append(BoundingBox(x1, y1, x2, y2, name, score, track_id))
            confidences[name] = max(confidences.get(name, 0), score)
    detected_boxes = tuple(boxes)
    context = tuple(
        Observation(frame.date, frame.image, {}, boxes=detected_boxes)
        for frame in frames[:-1]
    )
    latest = frames[-1]
    return (
        *context,
        Observation(latest.date, latest.image, confidences, boxes=detected_boxes),
    )


class YoloDetector:
    def __init__(
        self,
        model: YOLO,
        config: YoloConfig,
        sources: tuple[str, ...],
        options: InferenceOptions,
    ):
        self.model = model
        self.tracking = config.tracking
        self.sources = sources
        self.classes = resolve_classes(model.names, config.confidence)
        self._arguments: dict[str, Any] = {
            "conf": min(threshold for _, threshold in self.classes.values()),
            "classes": list(self.classes),
            "imgsz": config.imgsz,
            "rect": options.rectangular,
            "verbose": False,
        }
        if config.iou is not None:
            self._arguments["iou"] = config.iou
        if config.tracker is not None and config.tracking:
            self._arguments["tracker"] = config.tracker
        self._last_frames: dict[str, NDArray[np.uint8]] = {}

    def detect(self, frames: Frames) -> dict[str, tuple[Observation, ...]]:
        started = perf_counter()
        if self.tracking:
            sources = self.sources
            placeholder = np.zeros_like(next(iter(frames.values()))[-1].image)
            for source, batch in frames.items():
                self._last_frames[source] = batch[-1].image
            images = [self._last_frames.get(source, placeholder) for source in sources]
            source_batch = InMemoryStreamBatch(
                [f"source-{index}" for index in range(len(sources))], images
            )
            results = list(
                self.model.track(
                    # The SDK annotation omits LoadStreams instances, which its
                    # loader dispatch accepts. Keep the mismatch at this boundary.
                    source=cast(Any, source_batch),
                    persist=True,
                    stream=True,
                    batch=len(sources),
                    **self._arguments,
                )
            )
        else:
            sources = tuple(frames)
            images = [frames[source][-1].image for source in sources]
            results = list(
                self.model.predict(source=images, batch=len(images), **self._arguments)
            )
        mapped = {
            source: map_observations(result, frames[source], self.classes)
            for source, result in zip(sources, results, strict=True)
            if source in frames
        }
        logger.debug(
            "Inference completed for %d sources in %.3fs",
            len(mapped),
            perf_counter() - started,
        )
        return mapped


def resolve_classes(
    names: dict[int, str], confidence: float | dict[str, float]
) -> dict[int, tuple[str, float]]:
    if not isinstance(confidence, dict):
        return {index: (name, confidence) for index, name in names.items()}
    identifiers = {name: index for index, name in names.items()}
    unknown = set(confidence) - set(identifiers)
    if unknown:
        raise ValueError(
            f"Unknown YOLO classes: {', '.join(sorted(unknown))}. "
            f"Available classes: {', '.join(sorted(identifiers))}"
        )
    return {
        identifiers[name]: (name, threshold) for name, threshold in confidence.items()
    }


@contextmanager
def _restore_path_classes() -> Iterator[None]:
    # Ultralytics converts cross-platform checkpoint paths but leaves pathlib
    # mutated afterwards. Restore both platform classes after model preparation.
    windows, posix = pathlib.WindowsPath, pathlib.PosixPath
    try:
        yield
    finally:
        pathlib.WindowsPath, pathlib.PosixPath = windows, posix


@contextmanager
def open_detector(
    config: YoloConfig,
    onnx: OnnxConfig,
    sources: tuple[str, ...],
    build_type: str,
    options: InferenceOptions,
    cache_directory: pathlib.Path | None = None,
    report_status: ReportStatus = ignore_status,
) -> Iterator[YoloDetector]:
    """Prepare inference and own its model and tracking frames until shutdown."""
    loaded: YOLO | None = None
    detector: YoloDetector | None = None
    try:
        with _restore_path_classes():
            model_path = config.model
            native_mps = options.native_mps and model_path.endswith(".pt")
            if (
                cache_directory is not None
                and model_path.endswith(".pt")
                and build_type not in {"cuda", "tensorrt"}
                and not native_mps
            ):
                from aidetector.adapters.inference.prepared_models import prepare_onnx

                model_path = str(
                    prepare_onnx(
                        config,
                        onnx,
                        len(sources),
                        options,
                        cache_directory,
                        report_status,
                    )
                )
            report_status(
                StatusEvent(
                    "preparing", message="Loading the detection model on this computer…"
                )
            )
            try:
                loaded = YOLO(model_path, task=config.task)
            except ConnectionError:
                report_status(
                    StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP)
                )
                raise
            if (
                not model_path.endswith((".onnx", ".engine"))
                and build_type != "cuda"
                and not native_mps
            ):
                report_status(
                    StatusEvent(
                        "preparing", message="Preparing the model for this computer…"
                    )
                )
                exported = loaded.export(
                    format="engine" if build_type == "tensorrt" else "onnx",
                    batch=len(sources),
                    dynamic=True,
                    quantize=16 if options.half else None,
                    imgsz=config.imgsz,
                    simplify=True,
                    opset=onnx.opset,
                )
                loaded = YOLO(str(exported), task=config.task)
            # Ultralytics' .names property creates a temporary backend for exported
            # models. Retain its predictor here so class lookup and inference share
            # one session. This SDK-specific setup is covered by a real ONNX test.
            overrides = {
                **loaded.overrides,
                "quantize": 16 if native_mps or options.half else None,
            }
            if native_mps:
                overrides["device"] = "mps"
                logger.info("Native PyTorch inference on MPS (FP16)")
            loaded.predictor = loaded._smart_load("predictor")(
                overrides=overrides,
                _callbacks=loaded.callbacks,
            )
            loaded.predictor.setup_model(model=loaded.model, verbose=False)
        detector = YoloDetector(loaded, config, sources, options)
        yield detector
    finally:
        if detector is not None:
            detector._last_frames.clear()
        if loaded is not None:
            loaded.predictor = None
