import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from aidetector.adapters.inference.onnx import (
    REGISTRATION_TRACE_DELAY,
    ModelRequirements,
    inference_runtime,
    select_devices,
    select_providers,
    tensorrt_profiles,
)
from aidetector.configuration import OnnxConfig

ONNX_MODELS = (ModelRequirements("model.onnx", image_size=640, batch_size=1),)


@pytest.fixture
def windows_ml(monkeypatch):
    import faulthandler

    state = SimpleNamespace(libraries={}, lifecycle=[], watchdog=[])
    monkeypatch.setattr(
        faulthandler,
        "dump_traceback_later",
        lambda seconds: state.watchdog.append(seconds),
    )
    monkeypatch.setattr(
        faulthandler,
        "cancel_dump_traceback_later",
        lambda: state.watchdog.append("cancel"),
    )

    def prepare(requested):
        return {
            name: path
            for name, path in state.libraries.items()
            if requested is None or name == requested
        }

    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.prepare_windows_ml", prepare
    )
    return state


@pytest.fixture
def unavailable_windows_ml(monkeypatch):
    def prepare(requested):
        raise OSError("Windows acceleration package is unavailable offline")

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.prepare_windows_ml", prepare
    )


@pytest.mark.parametrize("ci_variable", [None, "CI", "GITHUB_ACTIONS"])
def test_optional_windows_provider_failure_falls_back_to_real_cpu_inference(
    tmp_path, unavailable_windows_ml, monkeypatch, ci_variable
):
    import numpy as np
    import onnxruntime as ort

    from tests.support.onnx_model import write_detection_model

    path = tmp_path / "model.onnx"
    write_detection_model(path)
    if ci_variable:
        monkeypatch.setenv(ci_variable, "true")
    notices = []
    with inference_runtime(
        OnnxConfig(), ONNX_MODELS, "windowsml", notices.append
    ) as options:
        assert options.half is False
        session = ort.InferenceSession(str(path))
        assert session.get_providers() == ["CPUExecutionProvider"]
        outputs = session.run(
            None, {"images": np.zeros((1, 3, 64, 64), dtype=np.float32)}
        )
        assert outputs[0].shape == (1, 1, 6)
    assert [event.kind for event in notices] == ["preparing", "notice"]
    assert "CPU" in notices[-1].message


def test_explicit_cpu_selection_skips_unavailable_windows_acceleration(
    unavailable_windows_ml,
):
    notices = []
    with inference_runtime(
        OnnxConfig(provider="CPUExecutionProvider"),
        ONNX_MODELS,
        "windowsml",
        notices.append,
    ) as options:
        assert options.half is False
    assert notices == []


def test_explicit_accelerator_does_not_silently_fall_back(unavailable_windows_ml):
    with (
        pytest.raises(OSError, match="unavailable offline"),
        inference_runtime(
            OnnxConfig(provider="OpenVINOExecutionProvider"), ONNX_MODELS, "windowsml"
        ),
    ):
        pytest.fail("An explicitly requested provider must remain a visible failure")


def test_invalid_model_is_not_treated_as_an_optional_acceleration_failure(
    tmp_path, unavailable_windows_ml
):
    import onnxruntime as ort
    from onnxruntime.capi.onnxruntime_pybind11_state import InvalidProtobuf

    path = tmp_path / "broken.onnx"
    path.write_text("not an ONNX model")
    with inference_runtime(OnnxConfig(), ONNX_MODELS, "windowsml"):
        with pytest.raises(InvalidProtobuf):
            ort.InferenceSession(str(path))


def test_explicit_provider_filters_out_other_registered_devices():
    gpu = SimpleNamespace(
        ep_name="OpenVINOExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    selection = select_providers(
        ["CPUExecutionProvider"], [gpu], "CPUExecutionProvider"
    )
    assert selection.names == ("CPUExecutionProvider",)
    assert selection.devices == ()
    assert selection.inference_options.half is False


def test_registered_devices_define_provider_order_and_inference_options():
    openvino = SimpleNamespace(
        ep_name="OpenVINOExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    tensorrt = SimpleNamespace(
        ep_name="NvTensorRTRTXExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    selection = select_providers(["CPUExecutionProvider"], [openvino, tensorrt], None)
    assert selection.names == (
        "NvTensorRTRTXExecutionProvider",
        "OpenVINOExecutionProvider",
    )
    assert selection.inference_options.half is True
    assert selection.inference_options.rectangular is False


@pytest.mark.parametrize("inference_fails", [False, True])
@pytest.mark.parametrize("missing_provider", [None, "first", "last"])
@pytest.mark.parametrize("explicit", [False, True])
def test_windows_ml_session_uses_registered_device_and_releases_libraries(
    monkeypatch,
    windows_ml,
    inference_fails,
    missing_provider,
    explicit,
    caplog,
):
    import logging
    import sys

    from onnxruntime.capi.onnxruntime_pybind11_state import Fail

    lifecycle = windows_ml.lifecycle
    sessions, options = [], []
    caplog.set_level(logging.INFO)

    class SessionOptions:
        def add_provider_for_devices(self, devices, settings):
            options.append((devices, settings))

    def session(path, **kwargs):
        sessions.append(kwargs)
        return "session"

    provider = SimpleNamespace(
        name="OpenVINOExecutionProvider", library_path="openvino.dll"
    )
    webgpu = SimpleNamespace(
        name="WebGpuExecutionProvider", library_path="onnxruntime_providers_webgpu.dll"
    )
    providers = [provider]
    if missing_provider == "first":
        providers.insert(0, webgpu)
    elif missing_provider == "last":
        providers.append(webgpu)
    windows_ml.libraries = {item.name: item.library_path for item in providers}

    def register(name, path):
        assert f"Registering Windows ML provider {name}: {path}" in caplog.text
        if name == webgpu.name:
            raise Fail(f'Error loading "{path}" which is missing. (Error 126)')
        lifecycle.append("register")

    device = SimpleNamespace(ep_name=provider.name, device=SimpleNamespace(type="GPU"))
    ort = SimpleNamespace(
        SessionOptions=SessionOptions,
        InferenceSession=session,
        get_available_providers=lambda: ["CPUExecutionProvider"],
        get_ep_devices=lambda: [device],
        register_execution_provider_library=register,
        unregister_execution_provider_library=lambda name: lifecycle.append(
            f"unregister:{name}"
        ),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    supplied = SessionOptions()

    outcome = (
        pytest.raises(RuntimeError, match="inference failed")
        if inference_fails
        else nullcontext()
    )
    with (
        outcome,
        inference_runtime(
            OnnxConfig(provider=provider.name if explicit else None),
            ONNX_MODELS,
            "windowsml",
        ) as inference,
    ):
        assert inference.half is False
        assert (
            ort.InferenceSession(
                "model.onnx", sess_options=supplied, providers=["CPUExecutionProvider"]
            )
            == "session"
        )
        assert sessions == [{"sess_options": supplied}]
        assert options[0][0] == [device]
        settings_path = Path(options[0][1]["load_config"])
        assert json.loads(settings_path.read_text()) == {
            "GPU": {"INFERENCE_PRECISION_HINT": "f32"}
        }
        if inference_fails:
            raise RuntimeError("inference failed")

    assert lifecycle == [
        "register",
        "unregister:OpenVINOExecutionProvider",
    ]
    if missing_provider and not explicit:
        assert "onnxruntime_providers_webgpu.dll" in caplog.text
        assert "Error 126" in caplog.text
    else:
        assert "unavailable" not in caplog.text
    assert ort.InferenceSession is session
    assert not settings_path.exists()
    assert "Windows ML provider OpenVINOExecutionProvider registered in" in caplog.text
    assert windows_ml.watchdog == [REGISTRATION_TRACE_DELAY, "cancel"] * (
        2 if missing_provider and not explicit else 1
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_windows_ml_registration_failure_is_observable(
    monkeypatch, windows_ml, caplog, tmp_path, explicit
):
    import logging

    import numpy as np
    import onnxruntime as ort
    from onnxruntime.capi.onnxruntime_pybind11_state import Fail

    from tests.support.onnx_model import write_detection_model

    def register(name, path):
        raise Fail(f'Error loading "{path}" which is missing. (Error 126)')

    monkeypatch.setattr(ort, "register_execution_provider_library", register)
    windows_ml.libraries = {
        "WebGpuExecutionProvider": "onnxruntime_providers_webgpu.dll"
    }
    caplog.set_level(logging.INFO)
    path = tmp_path / "model.onnx"
    write_detection_model(path)
    reports = []
    outcome = pytest.raises(Fail, match="Error 126") if explicit else nullcontext()
    with (
        outcome,
        inference_runtime(
            OnnxConfig(provider="WebGpuExecutionProvider" if explicit else None),
            ONNX_MODELS,
            "windowsml",
            reports.append,
        ) as options,
    ):
        assert not explicit
        assert options.half is False
        session = ort.InferenceSession(str(path))
        assert session.get_providers() == ["CPUExecutionProvider"]
        assert session.run(
            None, {"images": np.zeros((1, 3, 64, 64), dtype=np.float32)}
        )[0].shape == (1, 1, 6)
    assert [event.kind for event in reports] == [
        "preparing",
        "preparing",
        *([] if explicit else ["notice"]),
    ]
    if not explicit:
        assert "CPU" in reports[-1].message
        assert "Error 126" in caplog.text
    assert windows_ml.watchdog == [REGISTRATION_TRACE_DELAY, "cancel"]


def test_tensorrt_profiles_use_all_detector_dimensions_and_source_counts():
    models = (
        ModelRequirements("model.pt", image_size=320, batch_size=1),
        ModelRequirements("model.pt", image_size=640, batch_size=2),
    )
    assert tensorrt_profiles(models) == {
        "nv_profile_min_shapes": "images:1x3x320x320",
        "nv_profile_opt_shapes": "images:2x3x640x640",
        "nv_profile_max_shapes": "images:2x3x640x640",
    }


@pytest.mark.parametrize("build_type", ["default", "cuda", "tensorrt", "windowsml"])
def test_disabled_inference_does_not_load_onnx_runtime(monkeypatch, build_type):
    import sys

    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with inference_runtime(OnnxConfig(), (), build_type) as options:
        assert options.half is False
        assert options.rectangular is True
    assert tensorrt_profiles(()) == {}


@pytest.mark.parametrize("build_type", ["cuda", "tensorrt"])
def test_native_cuda_models_do_not_load_onnx_runtime(monkeypatch, build_type):
    import sys

    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    models = (
        ModelRequirements("model.pt", image_size=320, batch_size=1),
        ModelRequirements("model.engine", image_size=640, batch_size=2),
    )
    with inference_runtime(OnnxConfig(), models, build_type) as options:
        assert options.half is True
        assert options.rectangular is True
        assert options.native_mps is False


@pytest.mark.parametrize(
    "model_path", ["model.pt", "https://example.test/model.pt?signature=fake"]
)
def test_available_mps_skips_onnx_setup_for_native_checkpoints(monkeypatch, model_path):
    import sys

    import torch

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    models = (ModelRequirements(model_path, image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, "default") as options:
        assert options.native_mps is True


@pytest.mark.parametrize("platform, available", [("darwin", False), ("linux", True)])
def test_native_checkpoints_keep_onnx_when_mps_is_not_available_on_mac(
    monkeypatch, platform, available
):
    import sys

    import onnxruntime as ort
    import torch

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: available)
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    original = ort.InferenceSession
    models = (ModelRequirements("model.pt", image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, "default") as options:
        assert options.native_mps is False
        assert options.half is False
        assert ort.InferenceSession is not original
    assert ort.InferenceSession is original


@pytest.mark.parametrize("explicit_provider", [False, True])
def test_mixed_models_keep_onnx_and_explicit_provider_overrides_mps(
    monkeypatch, explicit_provider
):
    import sys

    import onnxruntime as ort
    import torch

    calls = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    monkeypatch.setattr(
        ort, "InferenceSession", lambda *args, **kwargs: calls.append(kwargs)
    )
    models = (
        ModelRequirements("model.pt", image_size=640, batch_size=1),
        ModelRequirements("model.onnx", image_size=320, batch_size=2),
    )
    config = OnnxConfig(provider="CPUExecutionProvider" if explicit_provider else None)
    with inference_runtime(config, models, "default") as options:
        assert options.native_mps is not explicit_provider
        assert options.half is False
        ort.InferenceSession("model.onnx")
    assert calls[0]["providers"] == [("CPUExecutionProvider", {})]


def test_unavailable_explicit_onnx_provider_is_not_replaced_by_available_mps(
    monkeypatch,
):
    import sys

    import onnxruntime as ort
    import torch

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    models = (ModelRequirements("model.pt", image_size=640, batch_size=1),)
    with (
        pytest.raises(ValueError, match="Configured ONNX provider is unavailable"),
        inference_runtime(
            OnnxConfig(provider="UnavailableProvider"), models, "default"
        ),
    ):
        pytest.fail("An explicit provider must not silently become native MPS")


def test_device_selection_prefers_openvino_gpu_and_puts_provider_last():
    cpu = SimpleNamespace(
        ep_name="OpenVINOExecutionProvider", device=SimpleNamespace(type="CPU")
    )
    gpu = SimpleNamespace(
        ep_name="OpenVINOExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    other = SimpleNamespace(
        ep_name="NvTensorRTRTXExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    assert select_devices([cpu, gpu, other]) == [other, gpu]


@pytest.mark.parametrize("inference_fails", [False, True])
def test_onnx_runtime_restores_session_factory_and_environment(
    monkeypatch, inference_fails
):
    import onnxruntime as ort

    calls = []

    def session(*args, **kwargs):
        calls.append(kwargs)
        return "session"

    monkeypatch.setattr(ort, "InferenceSession", session)
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    monkeypatch.setenv("ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS", "original")
    outcome = (
        pytest.raises(RuntimeError, match="inference failed")
        if inference_fails
        else nullcontext()
    )
    with (
        outcome,
        inference_runtime(OnnxConfig(), ONNX_MODELS, "default") as options,
    ):
        assert options.half is False
        assert ort.InferenceSession("model.onnx") == "session"
        assert calls[0]["providers"] == [("CPUExecutionProvider", {})]
        if inference_fails:
            raise RuntimeError("inference failed")
    import os

    assert ort.InferenceSession is session
    assert os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] == "original"


def test_unavailable_explicit_provider_fails_and_rolls_back_environment(monkeypatch):
    import os

    import onnxruntime as ort

    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    monkeypatch.delenv("ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS", raising=False)
    config = OnnxConfig(provider="UnavailableProvider")
    with (
        pytest.raises(ValueError, match="Configured ONNX provider is unavailable"),
        inference_runtime(config, ONNX_MODELS, "default"),
    ):
        pytest.fail("An unavailable provider must not silently fall back")
    assert "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS" not in os.environ


@pytest.mark.parametrize("build_type", ["cuda", "tensorrt"])
@pytest.mark.parametrize(
    "model_path",
    [
        "model.onnx",
        "https://example.test/model.onnx?signature=fake",
        "https://example.test/model.onnx#download",
    ],
)
def test_cuda_onnx_preloads_runtime_libraries(monkeypatch, build_type, model_path):
    import onnxruntime as ort

    calls = []
    monkeypatch.setattr(ort, "preload_dlls", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    models = (ModelRequirements(model_path, image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, build_type):
        assert calls == [{"directory": ""}]


@pytest.mark.parametrize("build_type", ["cuda", "tensorrt"])
def test_signed_onnx_url_still_checks_the_configured_provider(monkeypatch, build_type):
    import onnxruntime as ort

    monkeypatch.setattr(ort, "preload_dlls", lambda **kwargs: None)
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(ort, "get_ep_devices", list)
    original_session = ort.InferenceSession
    config = OnnxConfig(provider="UnavailableProvider")
    models = (
        ModelRequirements(
            "https://example.test/model.onnx?signature=fake",
            image_size=640,
            batch_size=1,
        ),
    )
    with (
        pytest.raises(ValueError, match="Configured ONNX provider is unavailable"),
        inference_runtime(config, models, build_type),
    ):
        pytest.fail("A query string must not bypass provider validation")
    assert ort.InferenceSession is original_session
