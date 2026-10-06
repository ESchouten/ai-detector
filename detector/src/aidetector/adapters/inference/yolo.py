from __future__ import annotations

import logging
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
from numpy.typing import NDArray
from ultralytics import YOLO
from ultralytics.data.loaders import LoadStreams, SourceTypes
from ultralytics.engine.results import Results

from aidetector.adapters.inference import MpsInferenceError
from aidetector.adapters.inference.export_settings import export_arguments
from aidetector.adapters.inference.model_assets import MODEL_DOWNLOAD_HELP
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.ports import Frames
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import OnnxConfig, YoloConfig
from aidetector.domain.models import BoundingBox, Frame, Observation

logger = logging.getLogger(__name__)
_MPS_LOCK = Lock()

if TYPE_CHECKING:
    from aidetector.adapters.inference.prepared_engines import EnginePreparation


@contextmanager
def _mps_inference() -> Iterator[None]:
    # PyTorch's MPS command encoders are shared across models and are not safe
    # under concurrent dispatch: https://github.com/pytorch/pytorch/issues/197805
    import torch

    with _MPS_LOCK:
        try:
            yield
            torch.mps.synchronize()
        except torch.AcceleratorError as error:
            raise MpsInferenceError(
                "Apple GPU inference failed; a fresh detector process is required."
            ) from error


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
        # Transfer once: reading individual GPU scalars repeatedly synchronizes MPS/CUDA.
        for box in result.boxes.cpu():
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


SUMMARY_SECONDS = 30


class YoloDetector:
    def __init__(
        self,
        model: YOLO,
        config: YoloConfig,
        sources: tuple[str, ...],
        options: InferenceOptions,
    ):
        self.model = model
        self._inference_scope = (
            _mps_inference
            if options.native_mps and config.model.endswith(".pt")
            else nullcontext
        )
        self.tracking = config.tracking
        self.sources = sources
        self.classes = resolve_classes(model.names, config.confidence)
        self._arguments: dict[str, Any] = {
            "conf": min(threshold for _, threshold in self.classes.values()),
            "classes": list(self.classes),
            "imgsz": config.imgsz,
            "rect": options.rectangular,
            "verbose": logger.isEnabledFor(logging.DEBUG),
        }
        if config.iou is not None:
            self._arguments["iou"] = config.iou
        if config.tracker is not None and config.tracking:
            self._arguments["tracker"] = config.tracker
        self._last_frames: dict[str, NDArray[np.uint8]] = {}
        # One line per batch would push everything else out of the log within a
        # day, so routine timing is summarised.
        self._summarised_at = perf_counter()
        self._batches = 0
        self._frames = 0
        self._busy_ms = 0.0
        self._slowest_ms = 0.0

    def detect(self, frames: Frames) -> dict[str, tuple[Observation, ...]]:
        started = perf_counter()
        with self._inference_scope():
            acquired = perf_counter()
            if self.tracking:
                sources = self.sources
                placeholder = np.zeros_like(next(iter(frames.values()))[-1].image)
                for source, batch in frames.items():
                    self._last_frames[source] = batch[-1].image
                images = [
                    self._last_frames.get(source, placeholder) for source in sources
                ]
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
                    self.model.predict(
                        source=images, batch=len(images), **self._arguments
                    )
                )
            predicted = perf_counter()
            mapped = {
                source: map_observations(result, frames[source], self.classes)
                for source, result in zip(sources, results, strict=True)
                if source in frames
            }
            mapping_ms = (perf_counter() - predicted) * 1000
        elapsed_ms = (perf_counter() - started) * 1000
        logger.debug(
            "%s time: %.1fms for %d frame(s), %.1fms/frame (%d active source(s)); "
            "GPU lock wait=%.1fms; SDK ms/frame=%s; result mapping=%.1fms; input shapes=%s",
            "Track" if self.tracking else "Predict",
            elapsed_ms,
            len(images),
            elapsed_ms / len(images),
            len(mapped),
            (acquired - started) * 1000,
            {
                stage: round(duration, 1)
                for stage, duration in results[0].speed.items()
                if duration is not None
            },
            mapping_ms,
            sorted({image.shape[:2] for image in images}),
        )
        self._batches += 1
        self._frames += len(images)
        self._busy_ms += elapsed_ms
        self._slowest_ms = max(self._slowest_ms, elapsed_ms)
        if perf_counter() - self._summarised_at >= SUMMARY_SECONDS:
            logger.info(
                "%s: %d frame(s) in %d batch(es) over %.0fs; %.1fms/frame on "
                "average, slowest batch %.1fms",
                "Tracking" if self.tracking else "Inference",
                self._frames,
                self._batches,
                perf_counter() - self._summarised_at,
                self._busy_ms / self._frames,
                self._slowest_ms,
            )
            self._summarised_at = perf_counter()
            self._batches = self._frames = 0
            self._busy_ms = self._slowest_ms = 0.0
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
    engines: EnginePreparation | None = None,
) -> Iterator[YoloDetector]:
    """Prepare inference and own its model and tracking frames until shutdown."""
    loaded: YOLO | None = None
    detector: YoloDetector | None = None
    try:
        with _restore_path_classes():
            model_path = config.model
            native_mps = options.native_mps and model_path.endswith(".pt")
            if (
                engines is not None
                and build_type == "cuda"
                and model_path.endswith(".pt")
                and cache_directory is not None
            ):
                engine = engines.prepare(
                    config,
                    onnx,
                    len(sources),
                    options,
                )
                if engine is not None:
                    loaded = _load_prepared_engine(
                        engine, config.task, options, report_status
                    )
            conversion = _export_format(model_path, build_type, native_mps)
            if (
                conversion == "onnx"
                and cache_directory is not None
                and model_path.endswith(".pt")
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
                conversion = None
            if loaded is None:
                loaded = _load_model(model_path, config.task, report_status)
            if conversion:
                report_status(
                    StatusEvent(
                        "preparing", message="Preparing the model for this computer…"
                    )
                )
                exported = loaded.export(
                    **export_arguments(config, onnx, len(sources), options, conversion)
                )
                loaded = YOLO(str(exported), task=config.task)
            if loaded.predictor is None:
                initialize_predictor(loaded, options, native_mps, report_status)
        detector = YoloDetector(loaded, config, sources, options)
        yield detector
    finally:
        if detector is not None:
            detector._last_frames.clear()
        if loaded is not None:
            loaded.predictor = None


def _load_prepared_engine(
    path: pathlib.Path,
    task: str,
    options: InferenceOptions,
    report_status: ReportStatus,
) -> YOLO | None:
    from aidetector.adapters.inference.prepared_engines import reject_engine

    model = _load_model(str(path), task, report_status)
    try:
        initialize_predictor(model, options, False, report_status)
        return model
    except (RuntimeError, ImportError, OSError) as error:
        model.predictor = None
        logger.warning(
            "Prepared TensorRT engine could not be loaded; using PyTorch/CUDA: %s",
            error,
        )
        try:
            reject_engine(path, str(error))
        except OSError:
            logger.exception("Could not record the rejected TensorRT engine")
        return None


def _export_format(
    path: str, build_type: str, native_mps: bool
) -> Literal["onnx", "engine"] | None:
    if path.endswith((".onnx", ".engine")) or build_type == "cuda" or native_mps:
        return None
    return "engine" if build_type == "tensorrt" else "onnx"


def _load_model(path: str, task: str, report_status: ReportStatus) -> YOLO:
    logger.info("Loading detection model: %s (task: %s)", pathlib.Path(path).name, task)
    report_status(
        StatusEvent(
            "preparing", message="Loading the detection model on this computer…"
        )
    )
    try:
        return YOLO(path, task=task)
    except ConnectionError:
        report_status(StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP))
        raise


def initialize_predictor(
    model: YOLO,
    options: InferenceOptions,
    native_mps: bool,
    report_status: ReportStatus = ignore_status,
) -> None:
    """Initialize the SDK backend once, for runtime inference or its benchmark."""
    # Ultralytics' .names property otherwise creates a temporary second backend.
    # Keep SDK-specific predictor setup here; open_detector owns its cleanup.
    overrides = {
        **model.overrides,
        "quantize": 16 if native_mps or options.half else None,
    }
    if native_mps:
        overrides["device"] = "mps"
        logger.info("MPS inference shares one GPU dispatch lock across detectors")
    model.predictor = model._smart_load("predictor")(
        overrides=overrides, _callbacks=model.callbacks
    )
    model.predictor.setup_model(
        model=model.model, verbose=logger.isEnabledFor(logging.DEBUG)
    )
    backend = model.predictor.model
    if backend.format == "onnx":
        logger.info(
            "ONNX model providers: %s; image tensor processing: %s; I/O binding: %s",
            backend.session.get_providers(),
            backend.device,
            backend.use_io_binding,
        )
    logger.info(
        "Inference backend ready: %s; image tensor device=%s; precision=%s",
        backend.format,
        backend.device,
        "FP16" if backend.fp16 else "FP32",
    )

    engine = (
        ", ".join(backend.session.get_providers())
        if backend.format == "onnx"
        else f"{backend.format.upper()} on {backend.device}"
    )
    report_status(StatusEvent("backend", message=engine))
