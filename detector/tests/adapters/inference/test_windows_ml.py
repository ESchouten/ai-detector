import json
import logging
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.inference.windows_ml import prepare_windows_ml
from aidetector.configuration import OnnxConfig
from tests.support.windows_ml_sdk import write_windows_ml_sdk

PROVIDER = "NvTensorRTRTXExecutionProvider"
OTHER_PROVIDER = "OpenVINOExecutionProvider"
SOURCE = Path(__file__).resolve().parents[3] / "src"


@pytest.fixture
def sdk_directory(tmp_path, monkeypatch, caplog):
    directory = tmp_path / "Windows SDK with spaces"
    directory.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(directory), str(SOURCE)]))
    caplog.set_level(logging.INFO)
    return directory


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_sdk_preparation_exits_before_registration_without_importing_winrt_in_parent(
    sdk_directory, monkeypatch, caplog, ready, explicit
):
    trace = write_windows_ml_sdk(
        sdk_directory,
        [(PROVIDER, "ready" if ready else "pending"), (OTHER_PROVIDER, "ready")],
    )
    lifecycle = []

    def register(name, path):
        assert not any(
            module.split(".")[0] in {"winui3", "winrt"} for module in sys.modules
        ), "PyWinRT must stay outside the ONNX process"
        assert Path(path) == sdk_directory / (name + ".dll")
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        assert events[-1][1] == "close", "SDK resources must close before registration"
        assert all(pid != os.getpid() for pid, _ in events)
        lifecycle.append("register:" + name)

    device = SimpleNamespace(ep_name=PROVIDER, device=SimpleNamespace(type="GPU"))
    ort = SimpleNamespace(
        InferenceSession=object(),
        get_available_providers=lambda: ["CPUExecutionProvider"],
        get_ep_devices=lambda: [device],
        register_execution_provider_library=register,
        unregister_execution_provider_library=lambda name: lifecycle.append(
            "unregister:" + name
        ),
    )
    # Load the real exception type before replacing the ONNX boundary.
    import_module("onnxruntime.capi.onnxruntime_pybind11_state")

    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    with inference_runtime(
        OnnxConfig(provider=PROVIDER if explicit else None),
        (ModelRequirements("model.onnx", image_size=640, batch_size=1),),
        "windowsml",
    ) as options:
        assert options.half is True
        assert options.rectangular is False
    assert lifecycle == [
        "register:" + PROVIDER,
        *(
            []
            if explicit
            else ["register:" + OTHER_PROVIDER, "unregister:" + OTHER_PROVIDER]
        ),
        "unregister:" + PROVIDER,
    ]
    assert ("Waiting for Windows ML provider" in caplog.text) is not ready
    assert "Windows ML helper diagnostics" in caplog.text


@pytest.mark.parametrize("behavior", ["timeout", "failed", "error", "missing_library"])
@pytest.mark.parametrize("explicit", [False, True])
def test_failed_preparation_is_observable_and_other_providers_remain_available(
    sdk_directory, caplog, behavior, explicit
):
    trace = write_windows_ml_sdk(
        sdk_directory, [(PROVIDER, behavior), (OTHER_PROVIDER, "ready")]
    )
    if explicit:
        with pytest.raises(RuntimeError, match="helper exited with status 1"):
            prepare_windows_ml(PROVIDER)
    else:
        assert prepare_windows_ml(None) == {
            OTHER_PROVIDER: str(sdk_directory / (OTHER_PROVIDER + ".dll"))
        }
    events = [json.loads(line)[1] for line in trace.read_text().splitlines()]
    assert events[0] == "initialize"
    assert events[-1] == "close"
    assert ("cancel:" + PROVIDER in events) is (behavior == "timeout")
    expected = (
        "timed out"
        if behavior == "timeout"
        else "did not supply a library path"
        if behavior == "missing_library"
        else "Provider download failed"
    )
    assert expected in caplog.text


def test_no_usable_provider_is_a_failure_not_an_empty_success(sdk_directory, caplog):
    write_windows_ml_sdk(sdk_directory, [(PROVIDER, "failed")])
    with pytest.raises(RuntimeError, match="helper exited with status 1"):
        prepare_windows_ml(None)
    assert "No Windows ML execution provider could be prepared" in caplog.text


def test_empty_catalog_is_valid_on_a_machine_without_accelerators(sdk_directory):
    write_windows_ml_sdk(sdk_directory, [])
    assert prepare_windows_ml(None) == {}


def test_blocked_helper_is_killed_and_reaped_with_its_diagnostics(
    sdk_directory, monkeypatch, caplog
):
    trace = write_windows_ml_sdk(sdk_directory, [(PROVIDER, "hang")])
    children = []
    start = subprocess.Popen

    def record_child(*args, **kwargs):
        process = start(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record_child)
    monkeypatch.setattr("aidetector.adapters.inference.windows_ml.HELPER_TIMEOUT", 5)
    with pytest.raises(TimeoutError, match="helper timed out after 5s"):
        prepare_windows_ml(None)
    assert len(children) == 1
    assert children[0].poll() is not None
    assert children[0].returncode != 0
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    helper_pid, last_event = events[-1]
    assert last_event == "wait:" + PROVIDER
    assert helper_pid != os.getpid()
    # Windows virtualenvs launch the interpreter through a separate redirector.
    # Its job object must terminate the real SDK process as well as the launcher.
    assert not psutil.pid_exists(helper_pid), "Windows ML helper survived its timeout"
    assert "Simulated native call blocked" in caplog.text
