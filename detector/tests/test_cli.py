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
        ("ftp://private:secret@camera/video.mp4", "Source URL is invalid"),
        ("rtsp://", "Source URL is invalid"),
        ("rtsp://private:secret@", "Source URL is invalid"),
        ("rtsp://private:secret@camera:99999/live", "Source URL is invalid"),
        ("rtsp://private:secret@camera with spaces/live", "Source URL is invalid"),
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


@pytest.mark.parametrize("live_preview", [False, True])
def test_cli_runs_no_model_detection_relative_to_config_with_separate_output(
    tmp_path, live_preview
):
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
    preview = ["--live-preview"] if live_preview else []
    process = run_cli(tmp_path, "--config", config, "--data-dir", output, *preview)
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
    assert (output / "live" / "frames").is_dir() is live_preview
    assert not (output / "live" / "session.json").exists()


@pytest.mark.parametrize("blocked_archive", [False, True])
def test_launcher_status_reports_real_capture_processing_and_archive_outcome(
    tmp_path, blocked_archive
):
    source = tmp_path / "input.png"
    assert cv2.imwrite(str(source), np.zeros((24, 32, 3), dtype=np.uint8))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "detectors": [
                    {"detection": {"source": str(source)}, "exporters": {"disk": {}}}
                ]
            }
        )
    )
    if blocked_archive:
        (tmp_path / "detections").write_text("Cannot create a directory here")
    process = run_cli(tmp_path, "--status-json")
    records = [
        json.loads(line.removeprefix("AIDETECTOR_STATUS "))
        for line in process.stdout.splitlines()
        if line.startswith("AIDETECTOR_STATUS ")
    ]
    events = [record["event"] for record in records]
    assert events[:2] == ["preparing", "ready"]
    assert events[2:4] == ["frame", "processed"]
    assert "inference" not in events
    assert events[-1] == ("recording_failed" if blocked_archive else "recording")
    assert records[3]["ruleId"] == "detector-1"
    assert records[-1]["ruleId"] == "detector-1"
    assert records[-1]["destinationId"] == "disk-1"
    assert process.returncode == (1 if blocked_archive else 0), process.stderr
    assert str(source) not in "\n".join(json.dumps(record) for record in records)


def test_launcher_inference_status_follows_real_onnx_prediction(tmp_path):
    from tests.support.onnx_model import write_detection_model

    source = tmp_path / "input.png"
    model = tmp_path / "model.onnx"
    assert cv2.imwrite(str(source), np.zeros((64, 64, 3), dtype=np.uint8))
    write_detection_model(model)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "onnx": {"provider": "CPUExecutionProvider"},
                "detectors": [
                    {
                        "detection": {"source": str(source)},
                        "yolo": {"model": str(model), "imgsz": 64, "frames_min": 1},
                        "exporters": {"disk": {}},
                    }
                ],
            }
        )
    )
    process = run_cli(tmp_path, "--status-json")
    assert process.returncode == 0, process.stderr
    records = [
        json.loads(line.removeprefix("AIDETECTOR_STATUS "))
        for line in process.stdout.splitlines()
        if line.startswith("AIDETECTOR_STATUS ")
    ]
    events = [record["event"] for record in records]
    assert events.index("frame") < events.index("inference") < events.index("recording")
    assert "processed" not in events


def test_launcher_keeps_shared_camera_rule_and_archive_failures_distinct(tmp_path):
    source = tmp_path / "input.png"
    assert cv2.imwrite(str(source), np.zeros((16, 16, 3), dtype=np.uint8))
    archive = tmp_path / "detections"
    archive.mkdir()
    (archive / "blocked").write_text("This destination cannot become a directory")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "detection": {"source": str(source)},
                        "exporters": {
                            "disk": [
                                {"directory": "blocked"},
                                {"directory": "first-ok"},
                            ]
                        },
                    },
                    {
                        "detection": {"source": str(source)},
                        "exporters": {"disk": {"directory": "second-ok"}},
                    },
                ]
            }
        )
    )
    process = run_cli(tmp_path, "--status-json")
    assert process.returncode == 1, process.stderr
    records = [
        json.loads(line.removeprefix("AIDETECTOR_STATUS "))
        for line in process.stdout.splitlines()
        if line.startswith("AIDETECTOR_STATUS ")
    ]
    outcomes = {
        (record["event"], record["ruleId"], record["destinationId"])
        for record in records
        if record["event"].startswith("recording")
    }
    assert outcomes == {
        ("recording_failed", "detector-1", "disk-1"),
        ("recording", "detector-1", "disk-2"),
        ("recording", "detector-2", "disk-1"),
    }


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
