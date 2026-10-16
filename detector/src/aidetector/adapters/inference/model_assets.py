"""Resolve model paths and cache the models that are named by URL."""

import hashlib
import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from time import perf_counter
from urllib.parse import urlsplit

from aidetector.adapters.diagnostics import resource_label
from aidetector.application.ports import ReportStatus, StatusEvent, ignore_status

logger = logging.getLogger(__name__)
MODEL_DOWNLOADING = "Downloading the detection model. This may take a few minutes…"
MODEL_DOWNLOAD_HELP = (
    "The detection model could not be downloaded. Check this computer's internet "
    "connection and try again. Your camera settings are saved. "
    "If it still fails, the model download may be unavailable."
)


def _download_failure(error: Exception) -> str:
    # The transport error's own text can contain credentials from the URL.
    import requests
    from urllib3.exceptions import NameResolutionError

    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"The model server returned HTTP {error.response.status_code}. Try again later or check the model URL."
    if isinstance(error, requests.exceptions.SSLError):
        return (
            "The model server's HTTPS certificate could not be verified. "
            "Check this computer's date and time and update AI Detector."
        )
    if isinstance(error, requests.Timeout):
        return "The connection to the model server timed out. Check the internet connection and try again."
    refused = error.args[0] if error.args else None
    if isinstance(getattr(refused, "reason", None), NameResolutionError):
        return "The model server's address could not be resolved. Check the internet connection and model URL."
    return (
        "Check the model URL and this computer's internet connection, then try again."
    )


def _download(url: str, target: Path, report_status: ReportStatus) -> None:
    # Keep offline path resolution and module imports free of the HTTP library.
    import requests

    try:
        with requests.get(
            url,
            stream=True,
            # A stalled transfer ends; a slow one may take as long as it needs.
            timeout=(30, 300),
            # requests has a variable of its own for this; the application has one.
            verify=os.environ.get("SSL_CERT_FILE", True),
        ) as response:
            response.raise_for_status()
            with target.open("wb") as file:
                for chunk in response.iter_content(2**20):
                    file.write(chunk)
    except requests.exceptions.ChunkedEncodingError:
        # The server sent less than it announced.
        target.unlink(missing_ok=True)
    except requests.RequestException as error:
        reason = _download_failure(error)
        report_status(
            StatusEvent(
                "preparation_failed",
                message=f"Model download failed. {reason} Your camera settings are saved.",
            )
        )
        raise RuntimeError(f"Model download failed: {reason}") from None


def resolve_model_path(
    value: str,
    directory: Path,
    cache: Path,
    report_status: ReportStatus = ignore_status,
) -> str:
    url = urlsplit(value)
    if url.scheme not in {"http", "https"}:
        requested = (directory / Path(value).expanduser()).resolve()
        if requested.exists() or Path(value).parent != Path("."):
            return str(requested)
        # Ultralytics recognizes stock weight names and downloads missing assets.
        # Give it a managed destination instead of the process working directory.
        cache.mkdir(parents=True, exist_ok=True)
        return str(cache / Path(value).name)
    name = PurePosixPath(url.path).name
    if not name.endswith((".pt", ".onnx", ".engine")):
        raise ValueError("Model URLs must identify a .pt, .onnx, or .engine file")
    cache = cache / hashlib.sha256(value.encode()).hexdigest()[:16]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.exists():
        logger.info("Model cache hit: %s (%d bytes)", target, target.stat().st_size)
        return str(target)
    report_status(StatusEvent("preparing", message=MODEL_DOWNLOADING))
    with tempfile.TemporaryDirectory(dir=cache, prefix="download-") as temporary:
        pending = Path(temporary) / name
        started = perf_counter()
        logger.info(
            "Model download started: %s; cache=%s", resource_label(value), target
        )
        _download(value, pending, report_status)
        if not pending.is_file() or not pending.stat().st_size:
            report_status(
                StatusEvent(
                    "preparation_failed",
                    message="The model download was incomplete. Your camera settings are saved; try again.",
                )
            )
            raise RuntimeError("Model download did not produce a complete file")
        pending.replace(target)
        logger.info(
            "Model download complete: %s; %d bytes in %.2fs",
            target,
            target.stat().st_size,
            perf_counter() - started,
        )
    return str(target)
