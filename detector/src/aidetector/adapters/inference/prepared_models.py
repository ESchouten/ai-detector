"""Reuse ONNX and Core ML exports of the same checkpoint and conversion settings."""

import errno
import logging
import shutil
import tempfile
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import onnx
import onnxslim
import torch
import ultralytics
from onnxruntime.transformers.onnx_model import OnnxModel
from ultralytics import YOLO
from ultralytics.utils.downloads import attempt_download_asset

from aidetector.adapters.inference.export_settings import (
    content_key,
    core_ml_arguments,
    export_arguments,
)
from aidetector.adapters.inference.model_assets import (
    MODEL_DOWNLOAD_HELP,
    MODEL_DOWNLOADING,
)
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import OnnxConfig, YoloConfig

logger = logging.getLogger(__name__)


def _cache_key(
    source: Path, task: str, arguments: dict, libraries: dict[str, str]
) -> str:
    identity = {
        "version": 1,
        "task": task,
        "export": arguments,
        "libraries": {
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
            **libraries,
        },
    }
    return content_key(identity, source)


def prepare_onnx(
    config: YoloConfig,
    onnx_config: OnnxConfig,
    batch: int,
    options: InferenceOptions,
    cache: Path,
    report_status: ReportStatus = ignore_status,
) -> Path:
    def validate(exported: Path) -> None:
        if options.half:
            # CPU FP16 conversion appends input casts after their consumers.
            # Use ORT's sorter; preserve external tensors and SDK metadata.
            logger.info("Ordering FP16 ONNX graph before validation")
            graph = onnx.load(exported, load_external_data=False)
            OnnxModel(graph).topological_sort()
            onnx.save(graph, exported)
        # Keep external tensor files beside the graph.
        onnx.checker.check_model(str(exported))

    return _prepare(
        config,
        export_arguments(config, onnx_config, batch, options),
        {"onnx": onnx.__version__, "onnxslim": onnxslim.__version__},
        "model.onnx",
        validate,
        cache,
        report_status,
    )


def prepare_core_ml(
    config: YoloConfig, cache: Path, report_status: ReportStatus = ignore_status
) -> Path:
    return _prepare(
        config,
        core_ml_arguments(config),
        {"coremltools": version("coremltools")},
        "model.mlpackage",
        lambda _exported: None,
        cache,
        report_status,
    )


def _prepare(
    config: YoloConfig,
    arguments: dict,
    libraries: dict[str, str],
    name: str,
    validate: Callable[[Path], None],
    cache: Path,
    report_status: ReportStatus,
) -> Path:
    # Stock weights still use Ultralytics' asset downloader. Explicit model URLs
    # have already been resolved by model_assets before entering this boundary.
    if not Path(config.model).is_file():
        report_status(StatusEvent("preparing", message=MODEL_DOWNLOADING))
    try:
        source = Path(attempt_download_asset(config.model))
    except ConnectionError:
        report_status(StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP))
        raise
    destination = cache / _cache_key(source, config.task, arguments, libraries)
    model_path = destination / name
    if model_path.exists():
        logger.info("Prepared model cache hit: %s", model_path)
        return model_path
    started = perf_counter()
    logger.info("Preparing %s: %s; export settings=%s", name, source.name, arguments)
    report_status(
        StatusEvent(
            "preparing",
            message="Preparing the model for this computer. This is saved for next time…",
        )
    )
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache, prefix="preparing-") as directory:
        pending = Path(directory)
        checkpoint = pending / "model.pt"
        shutil.copyfile(source, checkpoint)
        model = YOLO(str(checkpoint), task=config.task)
        exported = Path(model.export(**arguments))
        # Validate before publication. A failed/interrupted export never becomes
        # a reusable cache hit.
        validate(exported)
        checkpoint.unlink()
        try:
            pending.rename(destination)
        except OSError as error:
            # Another application process may have finished the same export.
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
    logger.info("%s prepared in %.2fs: %s", name, perf_counter() - started, model_path)
    return model_path
