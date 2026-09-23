"""Reuse portable ONNX exports of the same checkpoint and conversion settings."""

import errno
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import onnx
import onnxslim
import torch
import ultralytics
from ultralytics import YOLO
from ultralytics.utils.downloads import attempt_download_asset

from aidetector.adapters.inference.export_settings import export_arguments
from aidetector.adapters.inference.model_assets import MODEL_DOWNLOAD_HELP
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import OnnxConfig, YoloConfig


def _cache_key(source: Path, task: str, arguments: dict) -> str:
    identity = {
        "version": 1,
        "task": task,
        "export": arguments,
        "libraries": {
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
            "onnx": onnx.__version__,
            "onnxslim": onnxslim.__version__,
        },
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
    with source.open("rb") as checkpoint:
        for chunk in iter(lambda: checkpoint.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_onnx(
    config: YoloConfig,
    onnx_config: OnnxConfig,
    batch: int,
    options: InferenceOptions,
    cache: Path,
    report_status: ReportStatus = ignore_status,
) -> Path:
    # Stock weights still use Ultralytics' asset downloader. Explicit model URLs
    # have already been resolved by model_assets before entering this boundary.
    if not Path(config.model).is_file():
        report_status(
            StatusEvent(
                "preparing",
                message="Downloading the detection model. This may take a few minutes…",
            )
        )
    try:
        source = Path(attempt_download_asset(config.model))
    except ConnectionError:
        report_status(StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP))
        raise
    arguments = export_arguments(config, onnx_config, batch, options)
    destination = cache / _cache_key(source, config.task, arguments)
    model_path = destination / "model.onnx"
    if model_path.is_file():
        return model_path
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
        # Validate before publication and keep external tensor files beside the
        # graph. A failed/interrupted export never becomes a reusable cache hit.
        onnx.checker.check_model(str(exported))
        checkpoint.unlink()
        try:
            pending.rename(destination)
        except OSError as error:
            # Another application process may have finished the same export.
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
    return model_path
