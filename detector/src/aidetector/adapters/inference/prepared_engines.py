"""Prepare GPU-specific TensorRT engines without risking the inference process."""

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event
from time import monotonic, time

import torch
from filelock import FileLock
from ultralytics.utils.downloads import attempt_download_asset

from aidetector.adapters.inference.export_settings import export_arguments
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.status import ReportStatus, StatusEvent
from aidetector.configuration import OnnxConfig, YoloConfig

logger = logging.getLogger(__name__)
BUILD_TIMEOUT = 600.0
RETRY_DELAY = 86400.0


def engine_identity(source: Path, task: str, arguments: dict) -> str:
    gpu = torch.cuda.get_device_properties(0)
    identity = {
        "format": 1,
        "task": task,
        "export": arguments,
        "platform": platform.system(),
        "architecture": platform.machine(),
        "gpu": {
            "name": gpu.name,
            "capability": [gpu.major, gpu.minor],
            "memory": gpu.total_memory,
        },
        "driver": os.environ.get("AI_DETECTOR_NVIDIA_DRIVER", ""),
        "cuda": torch.version.cuda,
        "libraries": {
            name: version(name)
            for name in ("tensorrt-cu12", "torch", "ultralytics", "onnx", "onnxslim")
        },
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_engine(engine: Path, reason: str) -> None:
    """Defer a failed optimization, including across managed process restarts."""
    (engine.parent / "failure.txt").write_text(reason, encoding="utf-8")


def prepare_engine(
    config: YoloConfig,
    onnx: OnnxConfig,
    batch: int,
    options: InferenceOptions,
    cache: Path,
    report_status: ReportStatus,
    stop_requested: Event | None = None,
) -> Path | None:
    # Resolve stock weights through the SDK. Download/model failures are not
    # optimization failures and must remain visible to the caller.
    source = Path(attempt_download_asset(config.model))
    arguments = export_arguments(config, onnx, batch, options, "engine")
    arguments["device"] = 0
    try:
        identity = engine_identity(source, config.task, arguments)
    except PackageNotFoundError as error:
        logger.warning("TensorRT runtime unavailable; using PyTorch/CUDA: %s", error)
        return None
    destination = cache / "tensorrt" / identity
    engine = destination / "model.engine"
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with FileLock(str(destination / "build.lock"), timeout=0):
            failure = destination / "failure.txt"
            if failure.exists():
                if time() - failure.stat().st_mtime < RETRY_DELAY:
                    logger.warning(
                        "TensorRT preparation deferred; using PyTorch/CUDA: %s",
                        failure.read_text(encoding="utf-8"),
                    )
                    return None
                engine.unlink(missing_ok=True)
            if engine.is_file():
                logger.info("TensorRT engine cache hit: %s", engine)
                return engine
            reject_engine(engine, "An earlier TensorRT preparation did not complete")
            _build_engine(
                source, config.task, arguments, engine, report_status, stop_requested
            )
            failure.unlink(missing_ok=True)
            return engine
    except KeyboardInterrupt:
        (destination / "failure.txt").unlink(missing_ok=True)
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.warning(
            "TensorRT preparation unavailable; using PyTorch/CUDA: %s", error
        )
        return None


def _build_engine(source, task, arguments, engine, report_status, stop_requested):
    logger.info(
        "Preparing direct TensorRT FP16 engine: %s; settings=%s; timeout=%.0fs",
        source.name,
        arguments,
        BUILD_TIMEOUT,
    )
    with tempfile.TemporaryDirectory(
        dir=engine.parent, prefix="preparing-"
    ) as directory:
        pending = Path(directory)
        checkpoint = pending / "model.pt"
        shutil.copyfile(source, checkpoint)
        request = pending / "request.json"
        request.write_text(
            json.dumps(
                {"checkpoint": str(checkpoint), "task": task, "export": arguments}
            ),
            encoding="utf-8",
        )
        run_preparation(
            request, engine.parent / "build.log", report_status, stop_requested
        )
        (pending / "model.engine").replace(engine)
    logger.info("Direct TensorRT engine prepared and GPU-tested: %s", engine)


def run_preparation(
    request: Path,
    log_path: Path,
    report_status: ReportStatus,
    stop_requested: Event | None = None,
) -> None:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        # Source installs and the downloaded runtime both use this package root;
        # the latter intentionally does not install the app into site-packages.
        command.extend(
            [
                "-I",
                "-u",
                "-c",
                "import sys; sys.path.insert(0, sys.argv.pop(1)); from aidetector.cli import main; raise SystemExit(main())",
                str(Path(__file__).resolve().parents[3]),
            ]
        )
    command.extend(["--prepare-tensorrt", str(request)])
    stopped = stop_requested if stop_requested is not None else Event()
    with (
        log_path.open("w", encoding="utf-8") as output,
        log_path.open(encoding="utf-8", errors="replace") as tail,
    ):
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        ) as process:
            try:
                _wait_for_preparation(process, tail, report_status, stopped)
                if stopped.is_set():
                    raise KeyboardInterrupt
                if process.returncode:
                    raise RuntimeError(
                        f"TensorRT helper exited with status {process.returncode}; see {log_path}"
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                diagnostic = tail.read().strip()
                if diagnostic:
                    logger.info("TensorRT preparation:\n%s", diagnostic)


def _wait_for_preparation(process, tail, report_status, stopped):
    started, reported = monotonic(), -15.0
    while process.poll() is None:
        if stopped.is_set():
            raise KeyboardInterrupt
        elapsed = monotonic() - started
        if elapsed > BUILD_TIMEOUT:
            raise TimeoutError(f"TensorRT preparation exceeded {BUILD_TIMEOUT:.0f}s")
        if elapsed - reported >= 15:
            report_status(
                StatusEvent(
                    "preparing",
                    message=f"Optimizing NVIDIA detection ({elapsed:.0f}s). This is saved for next time…",
                )
            )
            reported = elapsed
        diagnostic = tail.read().strip()
        if diagnostic:
            logger.info("TensorRT preparation:\n%s", diagnostic)
        stopped.wait(0.25)
