import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import cv2
import numpy as np
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src"


def run_cli(directory, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "aidetector", *map(str, arguments)],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": str(SOURCE)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_help_and_version_work_without_configuration(tmp_path):
    assert run_cli(tmp_path, "--help").returncode == 0
    assert "default" in run_cli(tmp_path, "--version").stdout
    assert list(tmp_path.iterdir()) == []


def test_init_is_offline_and_does_not_overwrite_existing_config(tmp_path):
    created = run_cli(tmp_path, "--init-config")
    assert created.returncode == 0, created.stderr
    path = tmp_path / "config.json"
    original = path.read_bytes()
    refused = run_cli(tmp_path, "--init-config")
    assert refused.returncode == 2
    assert path.read_bytes() == original
    assert run_cli(tmp_path, "--check-config").returncode == 0
    assert path.read_bytes() == original


def test_invalid_and_missing_config_have_actionable_exit_status(tmp_path):
    assert run_cli(tmp_path).returncode == 2
    path = tmp_path / "config.json"
    path.write_text('{"detectors": []}')
    failed = run_cli(tmp_path, "--check-config")
    assert failed.returncode == 2
    assert "Invalid configuration" in failed.stderr
    assert path.read_text() == '{"detectors": []}'


@pytest.mark.parametrize(
    "sources, message",
    [
        (["video.mp4", "0"], "separate detector definitions"),
        ("camera", "camera index"),
        ("ftp://private:secret@camera/video.mp4", "Unsupported source URL"),
        ("rtsp://", "Source URL needs a host"),
        ("rtsp://private:secret@", "Source URL needs a host"),
        ("https://camera/photo.jpg", "local image file"),
    ],
)
def test_config_check_rejects_unsupported_sources_without_side_effects(
    tmp_path, sources, message
):
    document = json.dumps({"detectors": [{"detection": {"source": sources}}]})
    path = tmp_path / "config.json"
    path.write_text(document)
    process = run_cli(tmp_path, "--check-config")
    assert process.returncode == 2, process.stdout + process.stderr
    assert message in process.stderr
    assert "secret" not in process.stderr
    assert "Ultralytics" not in process.stdout + process.stderr
    assert path.read_text() == document
    assert list(tmp_path.iterdir()) == [path]


def test_cli_runs_no_model_detection_relative_to_config_with_separate_output(tmp_path):
    configured = tmp_path / "configured"
    configured.mkdir()
    image = configured / "input.png"
    assert cv2.imwrite(str(image), np.zeros((24, 32, 3), dtype=np.uint8))
    config = configured / "config.json"
    config.write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "detection": {"source": "input.png"},
                        "exporters": {"disk": {}},
                    }
                ]
            }
        )
    )
    output = tmp_path / "output"
    process = run_cli(tmp_path, "--config", config, "--data-dir", output)
    assert process.returncode == 0, process.stderr
    records = list(
        (output / "detections" / "unclassified" / "unvalidated").glob("*/metadata.json")
    )
    assert len(records) == 1
    metadata = json.loads(records[0].read_text())
    assert metadata["validated"] is None
    assert metadata["detections"] == 1
    assert "Processing finished: 1 event(s)" in process.stderr
    assert not (tmp_path / "detections").exists()
    assert not (configured / "detections").exists()


def test_cli_identifies_each_detector_when_the_same_destination_fails(tmp_path):
    assert cv2.imwrite(str(tmp_path / "input.png"), np.zeros((8, 8, 3), dtype=np.uint8))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "detection": {"source": "input.png"},
                        "exporters": {"disk": {"directory": "blocked"}},
                    }
                    for _ in range(2)
                ]
            }
        )
    )
    archive = tmp_path / "detections"
    archive.mkdir()
    (archive / "blocked").write_text("Existing file prevents archive creation")

    process = run_cli(tmp_path, "--config", config)

    assert process.returncode == 1, process.stderr
    failures = [
        line
        for line in process.stderr.splitlines()
        if "Delivery to disk-1 failed" in line
    ]
    assert len(failures) == 2
    assert any("[detector-1-delivery]" in line for line in failures)
    assert any("[detector-2-delivery]" in line for line in failures)
    assert "2 delivery failure(s)" in process.stderr


@pytest.mark.parametrize("control", ["signal", "stdin", "eof"])
@pytest.mark.parametrize("delivery,expected_status", [("success", 0), ("failure", 1)])
def test_launcher_shutdown_drains_events_and_preserves_delivery_failures(
    tmp_path, delivery, expected_status, control
):
    if control == "signal" and sys.platform == "win32":
        pytest.skip("Windows terminate does not dispatch POSIX SIGTERM")
    (tmp_path / "config.json").write_text(
        json.dumps({"detectors": [{"detection": {"source": "0"}}]})
    )
    script = Path(__file__).parent / "support" / "signal_process.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            delivery,
            *(["--control-stdin"] if control != "signal" else []),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(SOURCE)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = monotonic() + 10
        while (
            not (tmp_path / "ready").exists()
            and process.poll() is None
            and monotonic() < deadline
        ):
            sleep(0.01)
        assert (tmp_path / "ready").exists(), "Detector did not start"
        if control == "signal":
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(
            "stop\n" if control == "stdin" else "", timeout=10
        )
        assert process.returncode == expected_status, stdout + stderr
        assert (tmp_path / "flushed").read_text() == "unvalidated"
        assert (tmp_path / "health-stopped").exists()
        assert "Shutdown requested" in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
