import logging
import os
import sys
from contextlib import suppress
from pathlib import Path

import psutil
import pytest

from aidetector.adapters.inference.provider_probe import probe_provider

SOURCE = Path(__file__).resolve().parents[3] / "src"


@pytest.fixture
def probe_directory(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), str(SOURCE)]))
    caplog.set_level(logging.INFO)
    return tmp_path


def test_probe_runs_real_cpu_inference_without_configuration_or_runtime_files(
    probe_directory, caplog
):
    assert probe_provider("CPUExecutionProvider")
    assert "startup probe passed" in caplog.text
    assert list(probe_directory.iterdir()) == []


def test_probe_rejects_an_unavailable_provider_without_silent_cpu_fallback(
    probe_directory, caplog
):
    assert not probe_provider("UnavailableTestProvider")
    assert "Configured ONNX provider is unavailable" in caplog.text
    assert "exited with status 1" in caplog.text


def test_native_provider_exit_cannot_terminate_the_caller(probe_directory, caplog):
    (probe_directory / "onnxruntime.py").write_text("import os\nos._exit(47)\n")
    assert not probe_provider("DmlExecutionProvider")
    assert "exited with status 47" in caplog.text


def test_hung_native_provider_is_killed_and_reaped(
    probe_directory, monkeypatch, caplog
):
    (probe_directory / "onnxruntime.py").write_text(
        "import os\nfrom pathlib import Path\nfrom threading import Event\n"
        'Path("probe.pid").write_text(str(os.getpid()))\nEvent().wait()\n'
    )
    monkeypatch.setattr("aidetector.adapters.inference.provider_probe.PROBE_TIMEOUT", 3)
    assert not probe_provider("DmlExecutionProvider")
    pid = int((probe_directory / "probe.pid").read_text())
    assert pid != os.getpid()
    # Windows closes the virtualenv redirector's job before its child is reaped.
    with suppress(psutil.NoSuchProcess):
        psutil.Process(pid).wait(timeout=5)
    assert not psutil.pid_exists(pid)
    assert "timed out after 3 seconds" in caplog.text


def test_an_unlaunchable_probe_reports_its_failure(
    probe_directory, monkeypatch, caplog
):
    monkeypatch.setattr(sys, "executable", str(probe_directory / "missing-python"))
    assert not probe_provider("DmlExecutionProvider")
    assert "startup probe failed" in caplog.text
