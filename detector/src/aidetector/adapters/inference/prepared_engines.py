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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event, Thread
from time import monotonic, time

import torch
from filelock import FileLock
from ultralytics.utils.downloads import attempt_download_asset

from aidetector.adapters.inference.export_settings import export_arguments
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import OnnxConfig, YoloConfig

logger = logging.getLogger(__name__)
BUILD_TIMEOUT = 1800.0
RETRY_DELAY = 86400.0


class EnginePreparation:
    """Use cached engines now; build missing ones serially after monitoring opens."""

    def __init__(
        self,
        cache: Path,
        stop_requested: Event | None = None,
        report_status: ReportStatus = ignore_status,
    ):
        self.cache = cache
        self._stop = stop_requested if stop_requested is not None else Event()
        self._pending: list[Callable[[], Path | None]] = []
        self._report_status = report_status

    def prepare(
        self,
        config: YoloConfig,
        onnx: OnnxConfig,
        batch: int,
        options: InferenceOptions,
    ) -> Path | None:
        return prepare_engine(
            config,
            onnx,
            batch,
            options,
            self.cache,
            self._report,
            self._stop,
            schedule=self._pending.append,
        )

    @contextmanager
    def running(self) -> Iterator[None]:
        if not self._pending:
            yield
            return
        thread = Thread(target=self._run, name="tensorrt-preparation")
        thread.start()
        try:
            yield
        finally:
            self._stop.set()
            thread.join()

    def _run(self) -> None:
        prepared = False
        try:
            for prepare in self._pending:
                if self._stop.is_set():
                    return
                if prepare() is not None:
                    prepared = True
            if prepared and not self._stop.is_set():
                logger.info(
                    "TensorRT background preparation complete; new engines are ready for the next monitoring start"
                )
                self._report_status(StatusEvent("models_ready"))
        except KeyboardInterrupt:
            return
        except Exception:
            # An optional background worker must not stop active monitoring.
            logger.exception("Background TensorRT preparation failed")

    @staticmethod
    def _report(event: StatusEvent) -> None:
        # Preparation must not replace the running detectors' readiness/status.
        logger.info("Background TensorRT: %s", event.message)


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
    *,
    schedule: Callable[[Callable[[], Path | None]], None] | None = None,
) -> Path | None:
    # Resolve stock weights through the SDK. Download/model failures are not
    # optimization failures and must remain visible to the caller.
    source = Path(attempt_download_asset(config.model))
    arguments = export_arguments(config, onnx, batch, options, "engine")
    arguments["device"] = 0
    # The builder shares this GPU with monitoring. Limit its scratch workspace;
    # model weights and other allocations are additional to this SDK limit.
    arguments["workspace"] = 2
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
            if schedule is not None:
                schedule(
                    partial(
                        prepare_engine,
                        config,
                        onnx,
                        batch,
                        options,
                        cache,
                        report_status,
                        stop_requested,
                    )
                )
                logger.info(
                    "TensorRT optimization queued for %s; starting with PyTorch/CUDA",
                    source.name,
                )
                return None
            reject_engine(engine, "An earlier TensorRT preparation did not complete")
            try:
                _build_engine(
                    source,
                    config.task,
                    arguments,
                    engine,
                    report_status,
                    stop_requested,
                )
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                reject_engine(engine, str(error))
                raise
            failure.unlink(missing_ok=True)
            return engine
    except KeyboardInterrupt:
        (destination / "failure.txt").unlink(missing_ok=True)
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.warning(
            "TensorRT preparation unavailable; using PyTorch/CUDA: %s; build log: %s",
            error,
            destination / "build.log",
        )
        return None


def _build_engine(source, task, arguments, engine, report_status, stop_requested):
    logger.info(
        "Preparing direct TensorRT FP16 engine: %s; settings=%s; timeout=%.0fs",
        source.name,
        arguments,
        BUILD_TIMEOUT,
    )
    logger.info("TensorRT build log: %s", engine.parent / "build.log")
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
    if getattr(sys, "frozen", False):
        command.extend(["--prepare-tensorrt", str(request)])
    else:
        # Source installs and the downloaded runtime both use this package root;
        # the latter intentionally does not install the app into site-packages.
        # Enter the standard-library-only worker directly so its diagnostics
        # are active before any application or inference dependencies load.
        command.extend(
            [
                "-I",
                "-u",
                "-X",
                "faulthandler",
                "-c",
                "import sys; sys.path.insert(0, sys.argv.pop(1)); from pathlib import Path; from aidetector.adapters.inference.tensorrt_worker import run_helper; raise SystemExit(run_helper(Path(sys.argv[1])))",
                str(Path(__file__).resolve().parents[3]),
                str(request),
            ]
        )
    stopped = stop_requested if stop_requested is not None else Event()
    with (
        log_path.open("w", encoding="utf-8") as output,
        log_path.open(encoding="utf-8", errors="replace") as tail,
    ):
        output.write(f"Starting TensorRT helper: {sys.executable}\n")
        output.flush()
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        ) as process:
            logger.info("TensorRT helper process started; pid=%d", process.pid)
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
                    message=f"Preparing the TensorRT model ({elapsed:.0f}s elapsed, limit {BUILD_TIMEOUT:.0f}s). A completed model is saved for later starts.",
                )
            )
            reported = elapsed
        diagnostic = tail.read().strip()
        if diagnostic:
            logger.info("TensorRT preparation:\n%s", diagnostic)
        stopped.wait(0.25)
