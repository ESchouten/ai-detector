"""Resolve model paths and cache URL assets transferred by Ultralytics."""

import hashlib
import logging
import socket
import ssl
import tempfile
from pathlib import Path, PurePosixPath
from threading import get_ident
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from aidetector.adapters.diagnostics import resource_label
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status

logger = logging.getLogger(__name__)
MODEL_DOWNLOAD_HELP = (
    "The detection model could not be downloaded. Check this computer's internet "
    "connection and try again. Your camera settings are saved. "
    "If it still fails, the model download may be unavailable."
)


def _download_failure(error: ConnectionError) -> str:
    # Ultralytics chains its transport error, whose text can contain credentials.
    cause = error.__cause__
    if isinstance(cause, HTTPError):
        return f"The model server returned HTTP {cause.code}. Try again later or check the model URL."
    if isinstance(cause, URLError):
        cause = cause.reason
    if isinstance(cause, ssl.SSLCertVerificationError):
        return (
            "The model server's HTTPS certificate could not be verified. "
            "Check this computer's date and time and update AI Detector."
        )
    if isinstance(cause, socket.gaierror):
        return "The model server's address could not be resolved. Check the internet connection and model URL."
    if isinstance(cause, TimeoutError):
        return "The connection to the model server timed out. Check the internet connection and try again."
    return (
        "Check the model URL and this computer's internet connection, then try again."
    )


def _download(url: str, target: Path, report_status: ReportStatus) -> None:
    # Keep offline path resolution and module imports free of inference SDK setup.
    from ultralytics.utils.downloads import safe_download

    sdk_logger = logging.getLogger("ultralytics")
    thread = get_ident()

    def other_threads(record: logging.LogRecord) -> bool:
        return record.thread != thread

    # The SDK can log credentials embedded in URLs or transport exceptions.
    sdk_logger.addFilter(other_threads)
    try:
        # A single urllib attempt avoids the SDK's curl fallback, whose stderr
        # bypasses Python logging. Leave transfer and completeness checks to it.
        safe_download(
            url, file=target, unzip=False, progress=False, retry=0, min_bytes=0
        )
    except ConnectionError as error:
        reason = _download_failure(error)
        report_status(
            StatusEvent(
                "preparation_failed",
                message=f"Model download failed. {reason} Your camera settings are saved.",
            )
        )
        raise RuntimeError(f"Model download failed: {reason}") from None
    finally:
        sdk_logger.removeFilter(other_threads)


def resolve_model_path(
    value: str,
    directory: Path,
    cache: Path,
    report_status: ReportStatus = ignore_status,
    *,
    sha256: str | None = None,
) -> str:
    url = urlsplit(value)
    if url.scheme not in {"http", "https"}:
        requested = (directory / Path(value).expanduser()).resolve()
        if sha256 is not None:
            if not _matches_hash(requested, sha256):
                raise OSError("Local model failed its SHA-256 verification")
            return str(requested)
        if requested.exists() or Path(value).parent != Path("."):
            return str(requested)
        # Ultralytics recognizes stock weight names and downloads missing assets.
        # Give it a managed destination instead of the process working directory.
        cache.mkdir(parents=True, exist_ok=True)
        return str(cache / Path(value).name)
    name = PurePosixPath(url.path).name
    if not name.endswith((".pt", ".pth", ".onnx", ".engine", ".safetensors")):
        raise ValueError(
            "Model URLs must identify a .pt, .pth, .onnx, .engine, or .safetensors file"
        )
    cache = cache / hashlib.sha256(value.encode()).hexdigest()[:16]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.exists() and sha256 is not None and not _matches_hash(target, sha256):
        logger.warning("Discarding corrupt cached model: %s", target)
        target.unlink()
    if target.exists():
        logger.info("Model cache hit: %s (%d bytes)", target, target.stat().st_size)
        return str(target)
    report_status(
        StatusEvent(
            "preparing",
            message="Downloading the detection model. This may take a few minutes…",
        )
    )
    with tempfile.TemporaryDirectory(dir=cache, prefix="download-") as temporary:
        pending = Path(temporary) / name
        started = perf_counter()
        logger.info(
            "Model download started: %s; cache=%s", resource_label(value), target
        )
        _download(value, pending, report_status)
        # The SDK may return without a file after rejecting an empty/partial body.
        if not pending.is_file():
            report_status(
                StatusEvent(
                    "preparation_failed",
                    message="The model download was incomplete. Your camera settings are saved; try again.",
                )
            )
            raise RuntimeError("Model download did not produce a complete file")
        if sha256 is not None and not _matches_hash(pending, sha256):
            raise OSError("Downloaded model failed its SHA-256 verification")
        pending.replace(target)
        logger.info(
            "Model download complete: %s; %d bytes in %.2fs",
            target,
            target.stat().st_size,
            perf_counter() - started,
        )
    return str(target)


def _matches_hash(path: Path, expected: str) -> bool:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == expected
