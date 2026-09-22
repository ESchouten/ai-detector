"""Resolve model paths and cache URL assets transferred by Ultralytics."""

import hashlib
import logging
import tempfile
from pathlib import Path, PurePosixPath
from threading import get_ident
from urllib.parse import urlsplit

from aidetector.application.status import ReportStatus, StatusEvent, ignore_status

MODEL_DOWNLOAD_HELP = (
    "The detection model could not be downloaded. Check this computer's internet "
    "connection and try again. Your camera settings are saved. "
    "If it still fails, the model download may be unavailable."
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
    except ConnectionError:
        report_status(StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP))
        raise RuntimeError(
            "Model download failed; check its URL and connectivity"
        ) from None
    finally:
        sdk_logger.removeFilter(other_threads)


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
        return str(target)
    report_status(
        StatusEvent(
            "preparing",
            message="Downloading the detection model. This may take a few minutes…",
        )
    )
    with tempfile.TemporaryDirectory(dir=cache, prefix="download-") as temporary:
        pending = Path(temporary) / name
        _download(value, pending, report_status)
        # The SDK may return without a file after rejecting an empty/partial body.
        if not pending.is_file():
            report_status(
                StatusEvent("preparation_failed", message=MODEL_DOWNLOAD_HELP)
            )
            raise RuntimeError("Model download did not produce a complete file")
        pending.replace(target)
    return str(target)
