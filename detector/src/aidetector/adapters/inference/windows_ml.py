"""Discover Windows ML libraries without loading PyWinRT into the inference process."""

import json
import logging
import subprocess
import sys
from importlib import import_module
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)
PREPARATION_TIMEOUT = 120.0
HELPER_TIMEOUT = 150.0


def prepare_windows_ml(requested: str | None) -> dict[str, str]:
    """Run the SDK in a short-lived child; return ready provider names and DLL paths.

    PyWinRT conflicts with TensorRT RTX registration in the same process:
    https://ryzenai.docs.amd.com/en/latest/winml/troubleshooting.html
    """
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "aidetector"])
    command.append("--prepare-windows-ml")
    if requested is not None:
        command.append(requested)
    logger.info(
        "Preparing Windows ML in a separate process (timeout %.0fs)", HELPER_TIMEOUT
    )
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=HELPER_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as error:
        _log_helper_output(error.stderr)
        raise TimeoutError(
            f"Windows ML helper timed out after {HELPER_TIMEOUT:.0f}s"
        ) from error
    _log_helper_output(result.stderr)
    if result.returncode:
        raise RuntimeError(f"Windows ML helper exited with status {result.returncode}")
    return json.loads(result.stdout)


def _log_helper_output(output: str | bytes | None) -> None:
    # TimeoutExpired keeps captured bytes even when run() uses text mode.
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    if output:
        logger.info("Windows ML helper diagnostics:\n%s", output.rstrip())


def _discover_windows_ml(requested: str | None) -> dict[str, str]:
    """Prepare SDK providers in the helper process; never register ONNX libraries here."""
    bootstrap = import_module(
        "winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap"
    )
    # Background startup must not open an SDK installation dialog.
    with bootstrap.initialize(options=bootstrap.InitializeOptions.NONE):
        winml = import_module("winui3.microsoft.windows.ai.machinelearning")
        foundation = import_module("winrt.windows.foundation")
        logger.info("Discovering Windows ML execution providers")
        libraries: dict[str, str] = {}
        failed = False
        catalog = winml.ExecutionProviderCatalog.get_default()
        for provider in catalog.find_all_providers():
            if requested is not None and provider.name != requested:
                continue
            try:
                _prepare_provider(provider, winml, foundation)
                if not provider.library_path:
                    raise RuntimeError("Ready provider did not supply a library path")
                libraries[provider.name] = provider.library_path
            except (OSError, RuntimeError) as error:
                if requested is not None:
                    raise
                logger.warning(
                    "Windows ML provider %s unavailable: %s", provider.name, error
                )
                failed = True
        if failed and not libraries:
            raise RuntimeError("No Windows ML execution provider could be prepared")
        return libraries


def _prepare_provider(provider: Any, winml: Any, foundation: Any) -> None:
    state = provider.ready_state
    logger.info("Windows ML provider %s readiness: %s", provider.name, state)
    if state == winml.ExecutionProviderReadyState.READY:
        return
    started = perf_counter()
    logger.info("Requesting Windows ML preparation: %s", provider.name)
    operation = provider.ensure_ready_async()
    logger.info(
        "Waiting for Windows ML provider %s (timeout %.0fs)",
        provider.name,
        PREPARATION_TIMEOUT,
    )
    if operation.wait(PREPARATION_TIMEOUT) == foundation.AsyncStatus.STARTED:
        logger.warning("Cancelling timed-out Windows ML preparation: %s", provider.name)
        operation.cancel()
        raise TimeoutError(f"Windows ML preparation timed out for {provider.name}")
    logger.info("Reading Windows ML preparation result: %s", provider.name)
    result = operation.get_results()
    if result.status != winml.ExecutionProviderReadyResultState.SUCCESS:
        raise RuntimeError(
            f"Windows ML could not prepare {provider.name}: {result.diagnostic_text}"
        )
    logger.info(
        "Windows ML provider %s prepared in %.2fs",
        provider.name,
        perf_counter() - started,
    )


def run_helper(requested: str | None) -> int:
    """Internal, config-free CLI action. stdout is JSON; diagnostics go to stderr."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        libraries = _discover_windows_ml(requested)
    except (OSError, RuntimeError):
        logger.exception("Windows ML preparation failed")
        return 1
    print(json.dumps(libraries))
    return 0
