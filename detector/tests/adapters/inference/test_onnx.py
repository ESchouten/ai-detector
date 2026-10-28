import faulthandler
import json
import logging
import os
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime as ort
import pytest
from onnxruntime.capi.onnxruntime_pybind11_state import Fail, InvalidProtobuf

from aidetector.adapters.inference.onnx import (
    REGISTRATION_TRACE_DELAY,
    ModelRequirements,
    inference_runtime,
    select_devices,
    select_providers,
    tensorrt_profiles,
)
from aidetector.configuration import OnnxConfig
from tests.support.onnx_model import write_detection_model

ONNX_MODELS = (ModelRequirements("model.onnx", image_size=640, batch_size=1),)


@pytest.fixture
def windows_ml(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.probe_provider", lambda name: True
    )
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
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
            name: str(tmp_path / path)
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

    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.prepare_windows_ml", prepare
    )


@pytest.fixture
def cpu_provider_only(monkeypatch):
    monkeypatch.setattr(
        ort, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )


def test_optional_windows_provider_failure_falls_back_to_real_cpu_inference(
    tmp_path, unavailable_windows_ml
):
    path = tmp_path / "model.onnx"
    write_detection_model(path)
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


@pytest.mark.parametrize("supplied_options", [False, True])
def test_real_sessions_disable_idle_spinning_and_preserve_caller_options(
    tmp_path, supplied_options
):
    path = tmp_path / "model.onnx"
    write_detection_model(path)
    supplied = ort.SessionOptions() if supplied_options else None
    if supplied is not None:
        supplied.intra_op_num_threads = 2
        supplied.logid = "caller-options"
    with inference_runtime(
        OnnxConfig(provider="CPUExecutionProvider"), ONNX_MODELS, "default"
    ):
        session = ort.InferenceSession(str(path), sess_options=supplied)
        options = session.get_session_options()
        assert (
            options.get_session_config_entry("session.intra_op.allow_spinning") == "0"
        )
        assert (
            options.get_session_config_entry("session.inter_op.allow_spinning") == "0"
        )
        if supplied_options:
            assert options.intra_op_num_threads == 2
            assert options.logid == "caller-options"
        images = np.zeros((2, 3, 64, 64), dtype=np.float32)
        output = session.run(None, {"images": images})[0]
        np.testing.assert_allclose(output[:, 0, :], [[10, 10, 40, 50, 0.9, 0]] * 2)


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


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 2, 1, 0)])
@pytest.mark.parametrize("openvino_device", ["GPU", "CPU"])
def test_automatic_selection_excludes_webgpu_and_keeps_vendor_acceleration(
    order, openvino_device
):
    devices = [
        SimpleNamespace(ep_name=name, device=SimpleNamespace(type=kind))
        for name, kind in [
            ("NvTensorRTRTXExecutionProvider", "GPU"),
            ("OpenVINOExecutionProvider", openvino_device),
            ("WebGpuExecutionProvider", "GPU"),
            ("DmlExecutionProvider", "GPU"),
        ]
    ]
    selection = select_providers(
        ["CPUExecutionProvider"], [devices[i] for i in order], None
    )
    expected = [devices[0], devices[1]]
    assert selection.devices == tuple(expected)
    assert selection.names == tuple(device.ep_name for device in expected)


@pytest.mark.parametrize("explicit", [False, True])
def test_webgpu_requires_an_explicit_request_even_when_it_is_the_only_accelerator(
    explicit,
):
    device = SimpleNamespace(
        ep_name="WebGpuExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    selection = select_providers(
        [device.ep_name, "CPUExecutionProvider"],
        [device],
        device.ep_name if explicit else None,
    )
    assert selection.names == (
        (device.ep_name,) if explicit else ("CPUExecutionProvider",)
    )
    assert selection.devices == ((device,) if explicit else ())
    assert selection.inference_options.half is explicit


@pytest.mark.parametrize(
    "other",
    ["WebGpuExecutionProvider", "OpenVINOExecutionProvider", "QNNExecutionProvider"],
)
@pytest.mark.parametrize("has_devices", [False, True])
def test_directml_sessions_exclude_other_accelerators(other, has_devices):
    devices = [
        SimpleNamespace(ep_name=name, device=SimpleNamespace(type="GPU"))
        for name in ["DmlExecutionProvider", other]
    ]
    selection = select_providers(
        ["DmlExecutionProvider", other, "CPUExecutionProvider"],
        devices if has_devices else [],
        None,
    )
    if other != "WebGpuExecutionProvider" and has_devices:
        assert selection.names == (other,)
        assert selection.devices == (devices[1],)
    else:
        assert selection.names == (
            ("DmlExecutionProvider",)
            if has_devices
            else ("DmlExecutionProvider", "CPUExecutionProvider")
        )
        assert selection.devices == ((devices[0],) if has_devices else ())


def test_directml_uses_standard_cpu_fallback_instead_of_another_provider_cpu_device():
    dml = SimpleNamespace(
        ep_name="DmlExecutionProvider", device=SimpleNamespace(type="GPU")
    )
    openvino = SimpleNamespace(
        ep_name="OpenVINOExecutionProvider", device=SimpleNamespace(type="CPU")
    )
    selection = select_providers(
        ["DmlExecutionProvider", "CPUExecutionProvider"], [openvino, dml], None
    )
    assert selection.names == ("DmlExecutionProvider",)
    assert selection.devices == (dml,)


@pytest.mark.parametrize("failure", [None, "preparation", "registration"])
@pytest.mark.parametrize("has_device", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_builtin_directml_survives_optional_windows_ml_failure(
    monkeypatch, windows_ml, caplog, failure, has_device, explicit
):
    import logging
    import sys

    import onnxruntime as real_ort
    from onnxruntime.capi.onnxruntime_pybind11_state import Fail

    sessions, device_options, reports, preparations = [], [], [], []
    device = SimpleNamespace(
        ep_name="DmlExecutionProvider", device=SimpleNamespace(type="GPU")
    )

    class SessionOptions(real_ort.SessionOptions):
        def add_provider_for_devices(self, devices, settings):
            device_options.append((devices, settings))

    def session(path, **kwargs):
        sessions.append(kwargs)
        return "DirectML session"

    def prepare(requested):
        assert requested is None
        preparations.append(requested)
        if failure == "preparation":
            raise OSError("Optional Windows ML provider unavailable")
        if failure == "registration":
            return {"WebGpuExecutionProvider": "onnxruntime_providers_webgpu.dll"}
        return {}

    def register(name, path):
        raise Fail(f'Error loading "{path}" which is missing. (Error 126)')

    ort = SimpleNamespace(
        SessionOptions=SessionOptions,
        ExecutionMode=real_ort.ExecutionMode,
        InferenceSession=session,
        get_available_providers=lambda: [
            "CPUExecutionProvider",
            "DmlExecutionProvider",
        ],
        get_ep_devices=lambda: [device] if has_device else [],
        register_execution_provider_library=register,
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.prepare_windows_ml", prepare
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    caplog.set_level(logging.INFO)
    supplied = SessionOptions()
    supplied.enable_mem_pattern = True
    supplied.execution_mode = real_ort.ExecutionMode.ORT_PARALLEL
    with inference_runtime(
        OnnxConfig(provider="DmlExecutionProvider" if explicit else None),
        ONNX_MODELS,
        "windowsml",
        reports.append,
    ) as options:
        assert options.half is True
        assert (
            ort.InferenceSession("model.onnx", sess_options=supplied)
            == "DirectML session"
        )
        assert supplied.enable_mem_pattern is False
        assert supplied.execution_mode == real_ort.ExecutionMode.ORT_SEQUENTIAL
        if has_device:
            assert device_options == [([device], {})]
            assert "providers" not in sessions[0]
        else:
            assert sessions[0]["providers"] == [
                ("DmlExecutionProvider", {}),
            ] + ([] if explicit else [("CPUExecutionProvider", {})])
    assert "Built-in ONNX execution providers" in caplog.text
    notices = [report for report in reports if report.kind == "notice"]
    assert preparations == ([] if explicit else [None])
    assert len(notices) == int(failure is not None and not explicit)
    if notices:
        assert "built-in hardware acceleration" in notices[0].message


@pytest.mark.parametrize("explicit", [False, True])
def test_unusable_builtin_directml_is_probed_before_entering_the_inference_process(
    tmp_path, monkeypatch, windows_ml, explicit
):
    monkeypatch.setattr(
        ort,
        "get_available_providers",
        lambda: ["DmlExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.onnx.probe_provider", lambda name: False
    )
    path = tmp_path / "model.onnx"
    write_detection_model(path)
    notices = []
    runtime = inference_runtime(
        OnnxConfig(provider="DmlExecutionProvider" if explicit else None),
        ONNX_MODELS,
        "windowsml",
        notices.append,
    )
    if explicit:
        with pytest.raises(RuntimeError, match="DirectML could not start"), runtime:
            pytest.fail("An explicitly requested, unusable provider must fail visibly")
    else:
        with runtime as options:
            assert options.half is False
            session = ort.InferenceSession(str(path))
            assert session.get_providers() == ["CPUExecutionProvider"]
            outputs = session.run(
                None, {"images": np.zeros((1, 3, 64, 64), dtype=np.float32)}
            )
            assert outputs[0].shape == (1, 1, 6)
        assert any("DirectML could not start" in event.message for event in notices)


@pytest.mark.parametrize("failure", [None, "directory", "registration"])
@pytest.mark.parametrize("inference_fails", [False, True])
def test_windows_provider_dll_directories_survive_registration_until_runtime_cleanup(
    monkeypatch, windows_ml, tmp_path, failure, inference_fails
):
    import os
    import sys

    from onnxruntime.capi.onnxruntime_pybind11_state import Fail

    first, second = "WebGpuExecutionProvider", "OpenVINOExecutionProvider"
    directories = {name: str(tmp_path / name) for name in (first, second)}
    windows_ml.libraries = {
        name: str(Path(directory) / "provider.dll")
        for name, directory in directories.items()
    }
    active, events = [], []

    @contextmanager
    def add_directory(directory):
        if directory == directories[first] and failure == "directory":
            raise OSError("DLL directory unavailable")
        active.append(directory)
        events.append(("open", directory))
        try:
            yield
        finally:
            active.remove(directory)
            events.append(("close", directory))

    def register(name, path):
        assert str(Path(path).parent) in active
        if name == first and failure == "registration":
            raise Fail("Provider unavailable")
        events.append(("register", name))

    def unregister(name):
        assert directories[name] in active
        events.append(("unregister", name))

    device = SimpleNamespace(ep_name=second, device=SimpleNamespace(type="GPU"))
    ort = SimpleNamespace(
        InferenceSession=object(),
        get_available_providers=lambda: ["CPUExecutionProvider"],
        get_ep_devices=lambda: [device],
        register_execution_provider_library=register,
        unregister_execution_provider_library=unregister,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "add_dll_directory", add_directory, raising=False)
    outcome = (
        pytest.raises(RuntimeError, match="inference failed")
        if inference_fails
        else nullcontext()
    )
    with (
        outcome,
        inference_runtime(OnnxConfig(), ONNX_MODELS, "windowsml") as options,
    ):
        assert options.half is False
        assert active == ([directories[first]] if failure is None else []) + [
            directories[second]
        ]
        if inference_fails:
            raise RuntimeError("inference failed")
    assert active == []
    last = first if failure is None else second
    assert events[-2:] == [("unregister", last), ("close", directories[last])]
    assert (("unregister", first) in events) is (failure is None)


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
    lifecycle = windows_ml.lifecycle
    sessions, options = [], []
    caplog.set_level(logging.INFO)

    class SessionOptions(ort.SessionOptions):
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
    sdk = SimpleNamespace(
        SessionOptions=SessionOptions,
        InferenceSession=session,
        get_available_providers=lambda: ["CPUExecutionProvider"],
        get_ep_devices=lambda: [device],
        register_execution_provider_library=register,
        unregister_execution_provider_library=lambda name: lifecycle.append(
            f"unregister:{name}"
        ),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", sdk)
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
            sdk.InferenceSession(
                "model.onnx", sess_options=supplied, providers=["CPUExecutionProvider"]
            )
            == "session"
        )
        assert sessions == [{"sess_options": supplied}]
        assert (
            supplied.get_session_config_entry("session.intra_op.allow_spinning") == "0"
        )
        assert (
            supplied.get_session_config_entry("session.inter_op.allow_spinning") == "0"
        )
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
    assert sdk.InferenceSession is session
    assert not settings_path.exists()
    assert "Windows ML provider OpenVINOExecutionProvider registered in" in caplog.text
    assert windows_ml.watchdog == [REGISTRATION_TRACE_DELAY, "cancel"] * (
        2 if missing_provider and not explicit else 1
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_windows_ml_registration_failure_is_observable(
    monkeypatch, windows_ml, caplog, tmp_path, explicit
):
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


@pytest.mark.parametrize("build_type", ["default", "cuda", "windowsml"])
def test_disabled_inference_does_not_load_onnx_runtime(monkeypatch, build_type):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with inference_runtime(OnnxConfig(), (), build_type) as options:
        assert options.half is False
        assert options.rectangular is True


def test_native_cuda_models_do_not_load_onnx_runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    models = (
        ModelRequirements("model.pt", image_size=320, batch_size=1),
        ModelRequirements("model.engine", image_size=640, batch_size=2),
    )
    with inference_runtime(OnnxConfig(), models, "cuda") as options:
        assert options.half is True
        assert options.rectangular is True
        assert options.core_ml is False


@pytest.mark.parametrize(
    "model_path", ["model.pt", "https://example.test/model.pt?signature=fake"]
)
def test_a_mac_runs_checkpoints_on_core_ml_without_onnx_runtime(
    monkeypatch, model_path
):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    models = (ModelRequirements(model_path, image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, "default") as options:
        assert options.core_ml is True


@pytest.mark.parametrize(
    "system, provider, core_ml",
    [
        ("darwin", None, True),
        ("darwin", "CPUExecutionProvider", False),
        ("linux", None, False),
    ],
)
def test_onnx_models_and_an_explicit_provider_stay_with_onnx_runtime(
    monkeypatch, cpu_provider_only, system, provider, core_ml
):
    calls = []
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(
        ort, "InferenceSession", lambda *args, **kwargs: calls.append(kwargs)
    )
    models = (
        ModelRequirements("model.pt", image_size=640, batch_size=1),
        ModelRequirements("model.onnx", image_size=320, batch_size=2),
    )
    with inference_runtime(OnnxConfig(provider=provider), models, "default") as options:
        assert options.core_ml is core_ml
        assert options.half is False
        ort.InferenceSession("model.onnx")
    assert calls[0]["providers"] == [("CPUExecutionProvider", {})]


def test_unavailable_explicit_onnx_provider_is_not_replaced_by_core_ml(
    monkeypatch, cpu_provider_only
):
    monkeypatch.setattr(sys, "platform", "darwin")
    models = (ModelRequirements("model.pt", image_size=640, batch_size=1),)
    with (
        pytest.raises(ValueError, match="Configured ONNX provider is unavailable"),
        inference_runtime(
            OnnxConfig(provider="UnavailableProvider"), models, "default"
        ),
    ):
        pytest.fail("An explicit provider must not silently become Core ML")


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
    monkeypatch, cpu_provider_only, inference_fails
):
    calls = []

    def session(*args, **kwargs):
        calls.append(kwargs)
        return "session"

    monkeypatch.setattr(ort, "InferenceSession", session)
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
    assert ort.InferenceSession is session
    assert os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] == "original"


def test_unavailable_explicit_provider_fails_and_rolls_back_environment(
    monkeypatch, cpu_provider_only
):
    monkeypatch.delenv("ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS", raising=False)
    config = OnnxConfig(provider="UnavailableProvider")
    with (
        pytest.raises(ValueError, match="Configured ONNX provider is unavailable"),
        inference_runtime(config, ONNX_MODELS, "default"),
    ):
        pytest.fail("An unavailable provider must not silently fall back")
    assert "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS" not in os.environ


@pytest.mark.parametrize(
    "model_path",
    [
        "model.onnx",
        "https://example.test/model.onnx?signature=fake",
        "https://example.test/model.onnx#download",
    ],
)
def test_cuda_onnx_preloads_runtime_libraries(
    monkeypatch, cpu_provider_only, model_path
):
    calls = []
    monkeypatch.setattr(ort, "preload_dlls", lambda **kwargs: calls.append(kwargs))
    models = (ModelRequirements(model_path, image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, "cuda"):
        assert calls == [{"directory": ""}]


def test_cuda_onnx_runs_on_the_onnx_runtime_of_older_nvidia_drivers(
    monkeypatch, cpu_provider_only
):
    # nvidia-cuda12 keeps ONNX Runtime 1.20, which can neither preload nor list devices.
    monkeypatch.delattr(ort, "preload_dlls", raising=False)
    monkeypatch.delattr(ort, "get_ep_devices", raising=False)
    original_session = ort.InferenceSession
    models = (ModelRequirements("model.onnx", image_size=640, batch_size=1),)
    with inference_runtime(OnnxConfig(), models, "cuda"):
        assert ort.InferenceSession is not original_session


def test_signed_onnx_url_still_checks_the_configured_provider(
    monkeypatch, cpu_provider_only
):
    monkeypatch.setattr(ort, "preload_dlls", lambda **kwargs: None)
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
        inference_runtime(config, models, "cuda"),
    ):
        pytest.fail("A query string must not bypass provider validation")
    assert ort.InferenceSession is original_session
