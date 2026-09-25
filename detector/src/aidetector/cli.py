import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from threading import Event, Thread
from typing import TextIO

from aidetector.application.status import ReportStatus, ignore_status
from aidetector.configuration import ConfigurationError, load_config
from aidetector.version import REF_NAME, TYPE

logger = logging.getLogger(__name__)


def default_config_path() -> Path:
    directory = (
        Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    )
    return directory / "config.json"


def initial_config() -> dict:
    return {
        "$schema": f"https://raw.githubusercontent.com/ESchouten/ai-detector/{REF_NAME}/config/config.schema.json",
        "detectors": [
            {
                "detection": {"source": ["video.mp4"]},
                "yolo": {"model": "yolo11n.pt", "confidence": 0.5, "frames_min": 3},
                "exporters": {"disk": {}},
            }
        ],
    }


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def _read_stop_request(stream: TextIO, stopped: Event) -> None:
    for line in stream:
        if line.strip() == "stop":
            break
    stopped.set()


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect and validate events in video sources."
    )
    parser.add_argument(
        "--config", type=Path, default=default_config_path(), help="Configuration file"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Runtime data directory (defaults to the config directory)",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {REF_NAME} ({TYPE})"
    )
    parser.add_argument(
        "--control-stdin",
        action="store_true",
        help="Gracefully stop on a 'stop' line or EOF from the parent application",
    )
    parser.add_argument(
        "--status-json",
        action="store_true",
        help="Emit versioned operational status records for the application launcher",
    )
    parser.add_argument(
        "--live-preview",
        action="store_true",
        help="Publish analyzed frames only while the web application has a live viewer",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration without starting detection",
    )
    action.add_argument(
        "--init-config",
        action="store_true",
        help="Create an offline example configuration without overwriting a file",
    )
    return parser.parse_args(argv)


def _init_config(config_path: Path) -> int:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("x", encoding="utf-8") as output:
            json.dump(initial_config(), output, indent=2)
            output.write("\n")
    except OSError as error:
        print(f"Cannot create configuration: {error}", file=sys.stderr)
        return 2
    print(
        f"Created {config_path}. Configure sources and detection rules before running."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    config_path = args.config.expanduser().resolve()
    if args.init_config:
        return _init_config(config_path)
    try:
        config = load_config(config_path)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.check_config:
        print(f"Configuration valid: {len(config.detectors)} detector(s)")
        return 0

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    )
    previous_signal = signal.signal(signal.SIGTERM, _interrupt)
    try:
        directory = (
            args.data_dir.expanduser().resolve()
            if args.data_dir
            else config_path.parent
        )
        if getattr(sys, "frozen", False):
            # PyInstaller selects a fresh temporary font cache on every launch.
            # Matplotlib stores bundled font paths relatively, so reuse is safe.
            os.environ["MPLCONFIGDIR"] = str(directory / "cache" / "matplotlib")
        from aidetector.bootstrap import run_application

        stop_requested = None
        if args.control_stdin:
            stop_requested = Event()
            Thread(
                target=_read_stop_request,
                args=(sys.stdin, stop_requested),
                name="launcher-control",
                daemon=True,
            ).start()
        report_status: ReportStatus = ignore_status
        if args.status_json:
            from aidetector.adapters.operational_status import JsonStatusReporter

            report_status = JsonStatusReporter(sys.stdout)
        stats = run_application(
            config,
            config_path.parent,
            directory,
            stop_requested,
            report_status,
            live_preview=args.live_preview,
        )
        logger.info(
            "Processing finished: %d event(s), %d skipped, %d delivery failure(s), %d validation failure(s)",
            sum(item.events for item in stats),
            sum(item.skipped for item in stats),
            sum(item.delivery_failures for item in stats),
            sum(item.validation_failures for item in stats),
        )
        return 1 if any(item.failed for item in stats) else 0
    except KeyboardInterrupt:
        logger.info("Shutdown completed")
        return 0
    except ConfigurationError as error:
        logger.error("%s", error)
        return 2
    except Exception:
        logger.exception("Detector stopped after an application error")
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_signal)
