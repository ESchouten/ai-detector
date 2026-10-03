"""Useful startup context and bounded log files, without dumping configuration secrets."""

import json
import logging
import os
import platform
import re
import ssl
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from aidetector.adapters.operational_status import source_key
from aidetector.configuration import Config, DetectorConfig, source_kind

logger = logging.getLogger(__name__)
_URL = re.compile(r"(?:https?|rtsps?|tcp|udp)://[^\s\"'<>]+", re.IGNORECASE)
_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"


def resource_label(value: str) -> str:
    if "://" not in value:
        return Path(value).name
    # Model URLs and third-party exception text have not necessarily been validated.
    try:
        url = urlsplit(value)
        host = url.hostname or "unknown-host"
        authority = f"[{host}]" if ":" in host else host
        if url.port is not None:
            authority += f":{url.port}"
    except ValueError:
        return "<invalid URL>"
    # Paths can contain tokens too (for example Telegram's bot API).
    return f"{url.scheme}://{authority}"


def _secrets(config: Config) -> tuple[str, ...]:
    values: set[str] = set()
    headers: list[dict[str, str]] = []
    for detector in config.detectors:
        values.update(verifier.key for verifier in detector.vlm if verifier.key)
        headers.extend(verifier.headers for verifier in detector.vlm)
        values.update(exporter.token for exporter in detector.exporters.telegram)
        values.update(
            exporter.token for exporter in detector.exporters.webhook if exporter.token
        )
        for exporter in detector.exporters.webhook:
            headers.append(exporter.headers or {})
    if config.health is not None:
        headers.append(config.health.headers or {})
    for fields in headers:
        for name, value in fields.items():
            values.add(value)
            if name.lower() == "authorization":
                values.add(value.partition(" ")[2])
    return tuple(sorted(filter(None, values), key=len, reverse=True))


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__(_FORMAT)
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize the formatted traceback as well as the ordinary message.
        text = super().format(record)
        text = _URL.sub(lambda match: resource_label(match.group()), text)
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return text


@contextmanager
def diagnostic_logging(config: Config, directory: Path, level: str) -> Iterator[None]:
    root = logging.getLogger()
    previous_level = root.level
    formatter = DiagnosticFormatter(_secrets(config))
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    root.setLevel(level)
    file_handler = None
    try:
        path = directory / "logs" / "detector.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
        except OSError:
            logger.warning(
                "Could not open diagnostic log %s; using console logging",
                path,
                exc_info=True,
            )
        else:
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            logger.info("Diagnostic log: %s", path)
        yield
    finally:
        for handler in (console, file_handler):
            if handler is not None:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(previous_level)


def log_environment() -> None:
    logger.info(
        "Runtime: Python %s; %s %s; OS version=%s; architecture=%s; packaged=%s; pid=%d",
        platform.python_version(),
        platform.system(),
        platform.release(),
        platform.version(),
        platform.machine(),
        bool(getattr(sys, "frozen", False)),
        os.getpid(),
    )
    trust = ssl.get_default_verify_paths()
    certificate = os.environ.get("SSL_CERT_FILE", trust.openssl_cafile)
    logger.info(
        "HTTPS trust: %s; CA file=%s; file exists=%s; CA directory=%s",
        ssl.OPENSSL_VERSION,
        certificate,
        Path(certificate).is_file(),
        os.environ.get("SSL_CERT_DIR", trust.openssl_capath),
    )
    libraries = {}
    for name in (
        "ultralytics",
        "torch",
        "opencv-python",
        "onnxruntime",
        "onnxruntime-gpu",
        "onnxruntime-windowsml",
        "wasdk-microsoft-windows-ai-machinelearning",
        "winrt-runtime",
        "certifi",
    ):
        try:
            libraries[name] = version(name)
        except PackageNotFoundError:
            # Optional runtimes and distributions without copied package metadata.
            continue
    logger.info("Installed library versions: %s", json.dumps(libraries, sort_keys=True))


def log_detector_configuration(
    index: int, settings: DetectorConfig, sources: tuple[str, ...]
) -> None:
    # Explicit inclusion keeps future credential fields out of support logs.
    summary = {
        "sources": [
            {
                "id": source_key(source)[:12],
                "kind": source_kind(source),
                "address": resource_label(source),
            }
            for source in sources
        ],
        "capture": settings.detection.model_dump(
            include={"interval", "frames_width", "frame_retention"}
        ),
        "pending_events": settings.pending_events,
        "identity": settings.identity.model_dump()
        if settings.identity is not None
        else None,
        "yolo": None
        if settings.yolo is None
        else {
            **settings.yolo.model_dump(
                include={
                    "task",
                    "confidence",
                    "tracking",
                    "time_max",
                    "timeout",
                    "cooldown",
                    "include_trailing_time",
                    "frames_min",
                    "imgsz",
                    "iou",
                    "tracker",
                }
            ),
            "model": resource_label(settings.yolo.model),
            "model_id": source_key(settings.yolo.model)[:16],
        },
        "verification_enabled": bool(settings.active_vlm),
        "verification": [
            {
                "enabled": verifier.key is not None,
                "models": [
                    resource_label(model) if "://" in model else model
                    for model in verifier.model
                ],
                **verifier.model_dump(include={"strategy", "timeout", "attempts"}),
            }
            for verifier in settings.vlm
        ],
        "destinations": {
            kind: [
                exporter.model_dump(
                    include={
                        "confidence",
                        "export_rejected",
                        "strategy",
                        "alert_every",
                        "timeout",
                        "include_image",
                        "include_video",
                        "include_crop",
                        "include_plot",
                        "data_type",
                    }
                )
                for exporter in getattr(settings.exporters, kind)
            ]
            for kind in ("disk", "telegram", "webhook")
        },
    }
    logger.info(
        "Detector-%d configuration: %s", index, json.dumps(summary, sort_keys=True)
    )
