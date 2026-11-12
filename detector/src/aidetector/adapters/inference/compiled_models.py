"""Compile models for a Windows ML accelerator while DirectML keeps monitoring."""

import faulthandler
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, perf_counter, time
from typing import Any

from aidetector.adapters.inference.parent_control import exit_with_parent
from aidetector.application.ports import ReportStatus, StatusEvent

logger = logging.getLogger(__name__)
COMPILE_TIMEOUT = 1800.0
# Monitoring restarts a detector after two minutes without a finished batch.
FIRST_RUN_LIMIT = 60.0
RETRY_DELAY = 86400.0
TRACE_INTERVAL = 60.0


@dataclass(frozen=True)
class Accelerator:
    """A Windows ML device and its session settings, as the helper finds it again."""

    provider: str
    kind: str
    options: dict[str, str]


class CompiledModels:
    """Use tested compiled models now; compile missing ones after DirectML has started.

    A vendor provider may compile a model at its first inference, for minutes,
    and again in every new process. That compilation runs here in a helper
    process, and its result is cached and tested before monitoring uses it.
    """

    def __init__(
        self,
        cache: Path,
        accelerators: tuple[Accelerator, ...],
        libraries: dict[str, str],
        runtime_version: str,
        image_sizes: tuple[int, ...],
        batch: int,
        report_status: ReportStatus,
    ):
        self.cache = cache
        self._settings = {
            "accelerators": [asdict(accelerator) for accelerator in accelerators],
            "libraries": libraries,
            "image_sizes": list(image_sizes),
            "batch": batch,
        }
        self._identity = {
            "format": 1,
            "accelerators": [[item.provider, item.kind] for item in accelerators],
            "libraries": libraries,
            "onnxruntime": runtime_version,
            "image_sizes": list(image_sizes),
            "batch": batch,
        }
        self._report_status = report_status
        self._stop = Event()
        self._lock = Lock()
        self._pending: list[tuple[Path, Path]] = []
        self._threads: list[Thread] = []

    def model(self, source: Path) -> Path | None:
        """The model to open on the accelerator, or None to use DirectML for now."""
        destination = self._destination(source)
        ready = destination / "ready.json"
        if ready.is_file():
            compiled = json.loads(ready.read_text(encoding="utf-8"))["compiled"]
            model = destination / "model" / "model.onnx" if compiled else source
            logger.info("Windows ML model cache hit: %s", model)
            return model
        failure = destination / "failure.txt"
        if failure.is_file() and time() - failure.stat().st_mtime < RETRY_DELAY:
            logger.warning(
                "Windows ML compilation deferred; using DirectML: %s",
                failure.read_text(encoding="utf-8"),
            )
            return None
        with self._lock:
            self._pending.append((source, destination))
            if not any(thread.is_alive() for thread in self._threads):
                thread = Thread(target=self._run, name="windows-ml-compilation")
                self._threads.append(thread)
                thread.start()
        logger.info(
            "Windows ML compilation queued for %s; starting with DirectML", source.name
        )
        return None

    def reject(self, source: Path, reason: str) -> None:
        """Defer a model that the inference process could not open."""
        destination = self._destination(source)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "ready.json").unlink(missing_ok=True)
        (destination / "failure.txt").write_text(reason, encoding="utf-8")

    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join()

    def _destination(self, source: Path) -> Path:
        digest = hashlib.sha256(json.dumps(self._identity, sort_keys=True).encode())
        with source.open("rb") as model:
            key = hashlib.file_digest(model, lambda: digest).hexdigest()
        return self.cache / key

    def _run(self) -> None:
        prepared = False
        try:
            while not self._stop.is_set():
                with self._lock:
                    if not self._pending:
                        break
                    source, destination = self._pending.pop(0)
                try:
                    self._compile(source, destination)
                    prepared = True
                except (OSError, RuntimeError) as error:
                    logger.warning(
                        "Windows ML compilation unavailable; using DirectML: %s; log: %s",
                        error,
                        destination / "build.log",
                    )
            if prepared and not self._stop.is_set():
                logger.info(
                    "Windows ML compilation complete; the accelerator is used from the next monitoring start"
                )
                self._report_status(StatusEvent("models_ready"))
        except KeyboardInterrupt:
            return
        except Exception:
            # An optional background worker must not stop active monitoring.
            logger.exception("Background Windows ML compilation failed")

    def _compile(self, source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        failure = destination / "failure.txt"
        # A crash or forced stop must not lead to the same attempt at every start.
        failure.write_text(
            "An earlier Windows ML compilation did not complete", encoding="utf-8"
        )
        try:
            with tempfile.TemporaryDirectory(
                dir=destination, prefix="compiling-"
            ) as directory:
                pending = Path(directory)
                output = pending / "model" / "model.onnx"
                request = pending / "request.json"
                request.write_text(
                    json.dumps(
                        {**self._settings, "model": str(source), "output": str(output)}
                    ),
                    encoding="utf-8",
                )
                run_compilation(request, destination / "build.log", self._stop)
                compiled = output.is_file()
                if compiled:
                    output.parent.replace(destination / "model")
            (destination / "ready.json").write_text(
                json.dumps({"compiled": compiled}), encoding="utf-8"
            )
        except KeyboardInterrupt:
            failure.unlink(missing_ok=True)
            raise
        except (OSError, RuntimeError) as error:
            failure.write_text(str(error), encoding="utf-8")
            raise
        failure.unlink(missing_ok=True)
        logger.info(
            "Windows ML model %s and tested: %s",
            "compiled" if compiled else "needs no compilation",
            source,
        )


def run_compilation(request: Path, log_path: Path, stop_requested: Event) -> None:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "aidetector"])
    command.extend(["--compile-onnx-model", str(request)])
    with (
        log_path.open("w", encoding="utf-8") as output,
        log_path.open(encoding="utf-8", errors="replace") as tail,
        subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        ) as process,
    ):
        logger.info("Windows ML compilation helper started; pid=%d", process.pid)
        started, reported = monotonic(), 0.0
        try:
            while process.poll() is None:
                if stop_requested.is_set():
                    raise KeyboardInterrupt
                elapsed = monotonic() - started
                if elapsed > COMPILE_TIMEOUT:
                    raise TimeoutError(
                        f"Windows ML compilation exceeded {COMPILE_TIMEOUT:.0f}s"
                    )
                if elapsed - reported >= 60:
                    logger.info(
                        "Windows ML compilation running: %.0fs elapsed, limit %.0fs",
                        elapsed,
                        COMPILE_TIMEOUT,
                    )
                    reported = elapsed
                stop_requested.wait(0.25)
            if process.returncode:
                raise RuntimeError(
                    f"Windows ML compilation helper exited with status {process.returncode}"
                )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            diagnostic = tail.read().strip()
            if diagnostic:
                logger.info("Windows ML compilation:\n%s", diagnostic)


def picture_heights(size: int) -> list[int]:
    """Square, 4:3 and 16:9 camera pictures, letterboxed to the model's stride."""
    return sorted({size, -(-size * 3 // 4 // 32) * 32, -(-size * 9 // 16 // 32) * 32})


def compile_and_test(request: dict[str, Any]) -> None:
    import onnxruntime as ort

    for name, library in request["libraries"].items():
        if sys.platform == "win32":
            # Kept open until the helper exits.
            os.add_dll_directory(str(Path(library).parent))
        ort.register_execution_provider_library(name, library)
    devices = ort.get_ep_devices()

    def session_options() -> Any:
        options = ort.SessionOptions()
        for accelerator in request["accelerators"]:
            device = next(
                device
                for device in devices
                if device.ep_name == accelerator["provider"]
                and str(device.device.type) == accelerator["kind"]
            )
            options.add_provider_for_devices([device], accelerator["options"])
        return options

    model, output = request["model"], Path(request["output"])
    output.parent.mkdir()
    logger.info("Compiling %s for %s", model, request["accelerators"])
    started = perf_counter()
    try:
        ort.ModelCompiler(
            session_options(),
            model,
            embed_compiled_data_into_model=True,
            flags=ort.OrtCompileApiFlags.ERROR_IF_NO_NODES_COMPILED,
        ).compile_to_file(str(output))
        logger.info("Compiled in %.1fs: %s", perf_counter() - started, output)
        model = str(output)
    except Exception:
        # A provider without compiled models may still start fast enough; the
        # test decides. ONNX Runtime's errors share no narrower base.
        logger.exception("The accelerator did not compile the model; testing it as is")
        output.unlink(missing_ok=True)
    started = perf_counter()
    session = ort.InferenceSession(model, sess_options=session_options())
    logger.info("Opened %s in %.1fs", Path(model).name, perf_counter() - started)
    run_first_batches(session, request["image_sizes"], request["batch"])


def run_first_batches(session: Any, image_sizes: list[int], batch: int) -> None:
    """Every batch size and picture shape must finish its first run in time."""
    import numpy as np

    images = session.get_inputs()[0]
    dtype = np.float16 if images.type == "tensor(float16)" else np.float32
    shapes = [
        (count, height, size)
        for size in image_sizes
        for height in picture_heights(size)
        for count in range(1, batch + 1)
    ]
    for count, height, size in shapes:
        started = perf_counter()
        outputs = session.run(
            None, {images.name: np.zeros((count, 3, height, size), dtype)}
        )
        elapsed = perf_counter() - started
        logger.info("Test: batch=%d; image=%dx%d; %.2fs", count, height, size, elapsed)
        if elapsed > FIRST_RUN_LIMIT:
            raise RuntimeError(
                f"A first batch of {count} at {height}x{size} took {elapsed:.0f}s"
            )
        if not np.isfinite(np.asarray(outputs[0], dtype=np.float32)).all():
            raise RuntimeError("The accelerator returned invalid results")
    logger.info("Every batch size and picture shape ran within %.0fs", FIRST_RUN_LIMIT)


def run_helper(request_path: Path) -> int:
    """Internal CLI action: compile and test one model; the parent publishes it."""
    # A native compiler can hang without raising a Python exception.
    faulthandler.enable()
    faulthandler.dump_traceback_later(TRACE_INTERVAL, repeat=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    Thread(target=exit_with_parent, daemon=True, name="parent-control").start()
    try:
        compile_and_test(json.loads(request_path.read_text(encoding="utf-8")))
        return 0
    except Exception:
        logger.exception("Windows ML compilation failed")
        return 1
    finally:
        faulthandler.cancel_dump_traceback_later()
