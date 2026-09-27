import json
import logging

import pytest

from aidetector.adapters.diagnostics import (
    diagnostic_logging,
    log_detector_configuration,
    log_environment,
    resource_label,
)
from aidetector.adapters.operational_status import source_key
from aidetector.configuration import Config


@pytest.fixture
def configuration():
    return Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {
                        "source": "rtsp://camera-user:camera-password@192.0.2.10:554/private-path?token=camera-token",
                        "interval": 0.25,
                        "frames_width": 960,
                    },
                    "yolo": {
                        "model": "https://model-user:model-password@example.test/private-model.pt?token=model-token",
                        "confidence": {"test-class": 0.7},
                        "imgsz": 640,
                        "tracking": True,
                    },
                    "vlm": {
                        "model": "openai/test-model",
                        "key": "verifier-key",
                        "url": "https://example.test/private-api",
                        "prompt": "private-prompt",
                    },
                    "exporters": {
                        "telegram": {"token": "telegram-token", "chat": "private-chat"},
                        "webhook": {
                            "url": "https://example.test/private-webhook",
                            "token": "webhook-token",
                            "headers": {"Authorization": "Bearer header-secret"},
                            "body": "private-body",
                        },
                    },
                }
            ],
            "health": {
                "url": "https://example.test/private-health",
                "headers": {"X-Key": "health-secret"},
            },
        }
    )


@pytest.mark.parametrize(
    "value, label",
    [
        (
            "rtsp://user:password@192.0.2.10:554/token?key=secret",
            "rtsp://192.0.2.10:554",
        ),
        ("https://user:password@[::1]:443/private?key=secret", "https://[::1]:443"),
        ("https://[invalid", "<invalid URL>"),
        ("https://example.test:invalid/private", "<invalid URL>"),
        ("models/test.onnx", "test.onnx"),
        ("0", "0"),
    ],
)
def test_resource_labels_identify_the_host_without_url_credentials(value, label):
    assert resource_label(value) == label


def test_configuration_and_error_logs_are_useful_and_redacted_on_disk_and_console(
    tmp_path,
    configuration,
    capsys,
):
    settings = configuration.detectors[0]
    with diagnostic_logging(configuration, tmp_path, "INFO"):
        log_environment()
        log_detector_configuration(1, settings, settings.detection.source)
        try:
            raise RuntimeError(
                "Request failed HTTPS://user:exception-password@example.test/private?token=exception-token "
                "verifier-key telegram-token webhook-token Bearer header-secret health-secret header-secret"
            )
        except RuntimeError:
            logging.getLogger("aidetector.test").exception("Test transport failed")
    console = capsys.readouterr().err
    saved = (tmp_path / "logs/detector.log").read_text()
    for output in (console, saved):
        assert "Runtime: Python" in output
        assert "HTTPS trust:" in output
        assert "Installed library versions:" in output
        assert "Traceback (most recent call last)" in output
        assert "RuntimeError: Request failed https://example.test" in output
        assert "192.0.2.10:554" in output
        assert source_key(settings.detection.source[0])[:12] in output
        for secret in (
            "camera-user",
            "camera-password",
            "camera-token",
            "private-path",
            "model-user",
            "model-password",
            "model-token",
            "private-model",
            "verifier-key",
            "telegram-token",
            "webhook-token",
            "header-secret",
            "health-secret",
            "private-api",
            "private-prompt",
            "private-chat",
            "private-webhook",
            "private-body",
            "exception-password",
            "exception-token",
        ):
            assert secret not in output
        [record] = [
            line.split("configuration: ", 1)[1]
            for line in output.splitlines()
            if "Detector-1 configuration:" in line
        ]
        summary = json.loads(record)
        assert summary["capture"]["interval"] == 0.25
        assert summary["capture"]["frames_width"] == 960
        assert summary["yolo"]["confidence"] == {"test-class": 0.7}
        assert summary["yolo"]["tracking"] is True
        assert summary["verification"][0]["models"] == ["openai/test-model"]
        assert len(summary["destinations"]["telegram"]) == 1


def test_logs_survive_restart_without_duplicate_handlers(tmp_path, configuration):
    root = logging.getLogger()
    original_handlers, original_level = list(root.handlers), root.level
    for launch in range(2):
        with diagnostic_logging(configuration, tmp_path, "INFO"):
            logging.getLogger("aidetector.test").info("Launch marker %d", launch)
        assert root.handlers == original_handlers
        assert root.level == original_level
    saved = (tmp_path / "logs/detector.log").read_text()
    assert saved.count("Launch marker 0") == saved.count("Launch marker 1") == 1


def test_disk_logging_is_bounded_and_retains_the_latest_entries(
    tmp_path, configuration
):
    with diagnostic_logging(configuration, tmp_path, "INFO"):
        for index in range(32):
            logging.getLogger("aidetector.test").info(
                "Rotation marker %d %s", index, "x" * 524288
            )
    files = list((tmp_path / "logs").glob("detector.log*"))
    assert len(files) == 6
    assert sum(path.stat().st_size for path in files) <= 12 * 1024 * 1024
    assert "Rotation marker 31" in (tmp_path / "logs/detector.log").read_text()
    assert all("Rotation marker 0 " not in path.read_text() for path in files)


def test_unwritable_log_directory_keeps_console_diagnostics(
    tmp_path, configuration, capsys
):
    (tmp_path / "logs").write_text("Not a directory")
    with diagnostic_logging(configuration, tmp_path, "INFO"):
        logging.getLogger("aidetector.test").info("Monitoring can still start")
    output = capsys.readouterr().err
    assert "Could not open diagnostic log" in output
    assert "Monitoring can still start" in output
