import importlib.util
import os
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch
from filelock import FileLock
from ultralytics import YOLO

from aidetector import bootstrap
from aidetector.adapters.inference import prepared_engines
from aidetector.adapters.inference.export_settings import export_arguments
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.adapters.inference.prepared_engines import (
    EnginePreparation,
    engine_identity,
    prepare_engine,
    reject_engine,
    run_preparation,
)
from aidetector.adapters.inference.tensorrt_worker import build_and_test
from aidetector.adapters.inference.yolo import open_detector
from aidetector.configuration import Config, OnnxConfig, YoloConfig


@pytest.fixture
def gpu_builder(tmp_path, monkeypatch):
    source = tmp_path / "input.pt"
    source.write_bytes(b"checkpoint")
    gpu = SimpleNamespace(name="RTX fixture", major=8, minor=6, total_memory=8 << 30)
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda _index: gpu)
    monkeypatch.setattr(prepared_engines, "version", lambda _name: "1.0")
    monkeypatch.setenv("AI_DETECTOR_NVIDIA_DRIVER", "580.88")
    processes, commands, outcomes = [], [], []
    started = Event()
    popen = subprocess.Popen
    fixture = Path(__file__).parents[2] / "support/tensorrt_process.py"

    def start(command, **kwargs):
        assert all(process.poll() is not None for process in processes)
        commands.append(command)
        if outcomes:
            kwargs["env"] = {**os.environ, "TENSORRT_TEST_MODE": outcomes.pop(0)}
        process = popen([sys.executable, "-u", str(fixture), command[-1]], **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    return SimpleNamespace(
        source=source,
        gpu=gpu,
        commands=commands,
        processes=processes,
        started=started,
        outcomes=outcomes,
    )


def test_background_builds_wait_for_start_and_publish_reusable_engines_serially(
    tmp_path, gpu_builder
):
    cache = tmp_path / "cache"
    completed = Event()
    notices = []

    def report(event):
        notices.append(
            (event.kind, [process.poll() for process in gpu_builder.processes])
        )
        completed.set()

    engines = EnginePreparation(cache, report_status=report)
    configs = [
        YoloConfig(model=str(gpu_builder.source), imgsz=size) for size in (64, 96)
    ]
    for config in configs:
        assert engines.prepare(config, OnnxConfig(), 2, InferenceOptions()) is None
    assert gpu_builder.processes == []
    assert not list(cache.rglob("failure.txt"))
    with engines.running():
        assert completed.wait(10)
        assert len(list(cache.glob("tensorrt/*/model.engine"))) == 2
    assert notices == [("models_ready", [0, 0])]
    assert len(gpu_builder.processes) == 2
    assert all(process.poll() == 0 for process in gpu_builder.processes)
    assert not list(cache.rglob("failure.txt"))
    again = EnginePreparation(cache, report_status=report)
    for config in configs:
        assert again.prepare(config, OnnxConfig(), 2, InferenceOptions()).is_file()
    with again.running():
        pass
    assert len(gpu_builder.processes) == 2
    assert notices == [("models_ready", [0, 0])]


@pytest.mark.parametrize("successful_first", [True, False])
def test_background_completion_requires_a_new_engine_and_waits_for_failed_builds(
    tmp_path, gpu_builder, successful_first, caplog
):
    gpu_builder.outcomes.extend(["ready" if successful_first else "failed", "failed"])
    cache = tmp_path / "cache"
    completed = Event()
    notices = []

    def report(event):
        notices.append(
            (event.kind, [process.poll() for process in gpu_builder.processes])
        )
        completed.set()

    engines = EnginePreparation(cache, report_status=report)
    for size in (64, 96):
        engines.prepare(
            YoloConfig(model=str(gpu_builder.source), imgsz=size),
            OnnxConfig(),
            1,
            InferenceOptions(),
        )
    with engines.running():
        if successful_first:
            assert completed.wait(10)
            assert notices == [("models_ready", [0, 2])]
        else:
            deadline = monotonic() + 10
            while (
                caplog.text.count("TensorRT preparation unavailable") != 2
            ) and monotonic() < deadline:
                Event().wait(0.01)
            assert caplog.text.count("TensorRT preparation unavailable") == 2
            assert not completed.wait(0.1)
    assert len(gpu_builder.processes) == 2
    assert len(list(cache.glob("tensorrt/*/model.engine"))) == int(successful_first)
    assert len(list(cache.rglob("failure.txt"))) == (1 if successful_first else 2)
    if not successful_first:
        assert notices == []


@pytest.mark.parametrize("explicit_stop", [False, True])
def test_background_shutdown_reaps_the_builder_without_publishing_or_deferring(
    tmp_path, gpu_builder, monkeypatch, explicit_stop
):
    monkeypatch.setenv("TENSORRT_TEST_MODE", "blocked")
    cache = tmp_path / "cache"
    stop = Event()
    completions = []
    engines = EnginePreparation(cache, stop, completions.append)
    engines.prepare(
        YoloConfig(model=str(gpu_builder.source)), OnnxConfig(), 1, InferenceOptions()
    )
    with engines.running():
        assert gpu_builder.started.wait(5)
        assert gpu_builder.processes[0].poll() is None
        if explicit_stop:
            stop.set()
            gpu_builder.processes[0].wait(timeout=5)
    assert gpu_builder.processes[0].poll() is not None
    assert not list(cache.rglob("model.engine"))
    assert not list(cache.rglob("failure.txt"))
    assert not list(cache.rglob("preparing-*"))
    assert completions == []


@pytest.mark.parametrize("mode", ["blocked", "ready"])
def test_monitoring_opens_both_detectors_before_starting_background_preparation(
    tmp_path, gpu_builder, monkeypatch, mode
):
    monkeypatch.setenv("TENSORRT_TEST_MODE", mode)
    monkeypatch.setattr(bootstrap, "TYPE", "cuda")
    monkeypatch.setattr(prepared_engines, "gpu_available", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "inference_runtime",
        lambda *args: nullcontext(InferenceOptions()),
    )
    YOLO("yolo26n.yaml").save(gpu_builder.source)
    assert cv2.imwrite(str(tmp_path / "input.png"), np.zeros((64, 64, 3), np.uint8))
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "input.png"},
                    "yolo": {"model": str(gpu_builder.source), "imgsz": size},
                }
                for size in (64, 96)
            ]
        }
    )
    statuses = []
    completed = Event()

    def report(event):
        if event.kind == "ready":
            assert gpu_builder.processes == []
        if event.kind == "models_ready":
            completed.set()
        if event.kind in {"frame", "inference"}:
            assert gpu_builder.started.wait(5)
            if mode == "blocked":
                assert gpu_builder.processes[0].poll() is None
            else:
                assert completed.wait(10)
        statuses.append(event)

    results = bootstrap.run_application(
        config, tmp_path, tmp_path, report_status=report, prefer_tensorrt=True
    )
    assert len(results) == 2
    assert {event.rule_id for event in statuses if event.kind == "inference"} == {
        "detector-1",
        "detector-2",
    }
    ready = next(index for index, event in enumerate(statuses) if event.kind == "ready")
    assert all(event.kind != "preparing" for event in statuses[ready + 1 :])
    assert len(gpu_builder.processes) == (1 if mode == "blocked" else 2)
    assert gpu_builder.processes[0].poll() is not None
    assert len(list((tmp_path / "models").rglob("model.engine"))) == (
        0 if mode == "blocked" else 2
    )
    assert [event.kind for event in statuses].count("models_ready") == (
        0 if mode == "blocked" else 1
    )
    assert not list((tmp_path / "models").rglob("failure.txt"))


def test_successful_engine_is_published_once_without_modifying_checkpoint(
    tmp_path, gpu_builder
):
    progress = []
    config = YoloConfig(model=str(gpu_builder.source), imgsz=64)
    cache = tmp_path / "cache"
    options = InferenceOptions(half=True)
    first = prepare_engine(config, OnnxConfig(), 3, options, cache, progress.append)
    assert first is not None and first.read_bytes() == b"engine-from-checkpoint"
    assert (
        prepare_engine(config, OnnxConfig(), 3, options, cache, progress.append)
        == first
    )
    assert len(gpu_builder.commands) == 1
    assert gpu_builder.processes[0].returncode == 0
    assert gpu_builder.source.read_bytes() == b"checkpoint"
    assert not gpu_builder.source.with_suffix(".engine").exists()
    assert not list(cache.rglob("preparing-*"))
    assert not list(cache.rglob("failure.txt"))
    assert all(event.kind == "preparing" for event in progress)
    assert all("limit" in event.message for event in progress)
    assert "GPU builder fixture: ready" in (first.parent / "build.log").read_text()
    gpu_builder.source.write_bytes(b"new checkpoint")
    second = prepare_engine(config, OnnxConfig(), 3, options, cache, progress.append)
    assert second is not None and second != first
    assert first.is_file() and second.is_file()
    assert second.read_bytes() == b"engine-from-new checkpoint"
    assert len(gpu_builder.commands) == 2


@pytest.mark.parametrize(
    "change", ["weights", "size", "batch", "precision", "gpu", "driver", "runtime"]
)
def test_engine_identity_is_specific_to_weights_settings_gpu_and_runtime(
    gpu_builder, monkeypatch, change
):
    config = YoloConfig(model=str(gpu_builder.source), imgsz=64)
    options = InferenceOptions(half=True)
    arguments = export_arguments(config, OnnxConfig(), 1, options, "engine")
    first = engine_identity(gpu_builder.source, config.task, arguments)
    assert engine_identity(gpu_builder.source, config.task, arguments) == first
    batch = 1
    if change == "weights":
        gpu_builder.source.write_bytes(b"new checkpoint")
    elif change == "size":
        config = config.model_copy(update={"imgsz": 128})
    elif change == "batch":
        batch = 2
    elif change == "precision":
        options = replace(options, half=False)
    elif change == "gpu":
        gpu_builder.gpu.name = "another GPU"
    elif change == "driver":
        monkeypatch.setenv("AI_DETECTOR_NVIDIA_DRIVER", "581.00")
    else:
        monkeypatch.setattr(prepared_engines, "version", lambda _name: "2.0")
    arguments = export_arguments(config, OnnxConfig(), batch, options, "engine")
    assert engine_identity(gpu_builder.source, config.task, arguments) != first
    assert gpu_builder.processes == []


@pytest.mark.parametrize("mode", ["failed", "crashed", "blocked"])
def test_failed_or_stalled_builder_is_reaped_and_deferred_across_restarts(
    tmp_path, gpu_builder, monkeypatch, caplog, mode
):
    monkeypatch.setenv("TENSORRT_TEST_MODE", mode)
    monkeypatch.setattr(prepared_engines, "BUILD_TIMEOUT", 0.5)
    config = YoloConfig(model=str(gpu_builder.source))
    cache = tmp_path / "cache"
    for _ in range(2):
        assert (
            prepare_engine(
                config, OnnxConfig(), 1, InferenceOptions(), cache, lambda _: None
            )
            is None
        )
    assert len(gpu_builder.commands) == 1
    assert gpu_builder.processes[0].poll() is not None
    assert not list(cache.rglob("*.engine"))
    assert not list(cache.rglob("preparing-*"))
    assert len(list(cache.rglob("failure.txt"))) == 1
    assert "using PyTorch/CUDA" in caplog.text
    assert "deferred" in caplog.text
    if mode == "blocked":
        assert "exceeded" in caplog.text
        assert "exceeded" in next(cache.rglob("failure.txt")).read_text()


def test_cancelled_builder_is_reaped_and_next_start_can_retry(
    tmp_path, gpu_builder, monkeypatch
):
    monkeypatch.setenv("TENSORRT_TEST_MODE", "blocked")
    stop = Event()
    config = YoloConfig(model=str(gpu_builder.source))
    cache = tmp_path / "cache"
    with pytest.raises(KeyboardInterrupt):
        prepare_engine(
            config,
            OnnxConfig(),
            1,
            InferenceOptions(),
            cache,
            lambda _: stop.set(),
            stop,
        )
    assert gpu_builder.processes[0].poll() is not None
    assert not list(cache.rglob("*.engine"))
    assert not list(cache.rglob("failure.txt"))
    assert not list(cache.rglob("preparing-*"))
    monkeypatch.delenv("TENSORRT_TEST_MODE")
    assert prepare_engine(
        config, OnnxConfig(), 1, InferenceOptions(), cache, lambda _: None
    ).is_file()


def test_rejected_cached_engine_waits_then_is_rebuilt(tmp_path, gpu_builder):
    config = YoloConfig(model=str(gpu_builder.source))
    args = (
        config,
        OnnxConfig(),
        1,
        InferenceOptions(),
        tmp_path / "cache",
        lambda _: None,
    )
    engine = prepare_engine(*args)
    reject_engine(engine, "GPU rejected the cached engine")
    assert prepare_engine(*args) is None
    assert len(gpu_builder.commands) == 1
    os.utime(engine.parent / "failure.txt", (0, 0))
    assert prepare_engine(*args) == engine
    assert len(gpu_builder.commands) == 2


def test_concurrent_builder_does_not_block_monitoring(tmp_path, gpu_builder):
    config = YoloConfig(model=str(gpu_builder.source))
    args = (
        config,
        OnnxConfig(),
        1,
        InferenceOptions(),
        tmp_path / "cache",
        lambda _: None,
    )
    engine = prepare_engine(*args)
    engine.unlink()
    with FileLock(str(engine.parent / "build.lock")):
        assert prepare_engine(*args) is None
    assert len(gpu_builder.commands) == 1


def test_model_download_failure_is_not_hidden_by_optional_optimization(
    tmp_path, monkeypatch
):
    def download(_model):
        raise ConnectionError("Checkpoint download failed")

    monkeypatch.setattr(prepared_engines, "attempt_download_asset", download)
    with pytest.raises(ConnectionError, match="Checkpoint download failed"):
        prepare_engine(
            YoloConfig(model="yolo26n.pt"),
            OnnxConfig(),
            1,
            InferenceOptions(),
            tmp_path,
            lambda _: None,
        )


def test_builder_parent_pipe_closes_without_leaving_an_orphan():
    command = [
        sys.executable,
        "-c",
        "from aidetector.adapters.inference.tensorrt_worker import exit_with_parent; print('ready', flush=True); exit_with_parent()",
    ]
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    ) as process:
        try:
            assert process.stdout.readline().strip() == "ready"
            process.stdin.close()
            assert process.wait(timeout=10) == 1
        finally:
            if process.poll() is None:
                process.kill()


@pytest.mark.parametrize(
    ("request_text", "error"),
    [("invalid JSON", "JSONDecodeError"), ("{}", "KeyError: 'export'")],
)
def test_helper_imports_with_parent_pipe_open_and_reports_startup_failures(
    tmp_path, caplog, monkeypatch, request_text, error
):
    # A valid JSON object reaches real cold native imports without a GPU/model.
    # The parent pipe stays open: blocking reads previously deadlocked NumPy
    # on Windows. Bound this regression independently of the engine deadline.
    monkeypatch.setattr(prepared_engines, "BUILD_TIMEOUT", 60)
    request = tmp_path / "request.json"
    request.write_text(request_text, encoding="utf-8")
    log = tmp_path / "build.log"
    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="status 1"):
        run_preparation(request, log, lambda _: None)
    diagnostic = log.read_text()
    assert "Starting TensorRT helper:" in diagnostic
    assert "TensorRT helper started; pid=" in diagnostic
    assert error in diagnostic
    assert error in caplog.text
    if request_text == "{}":
        assert "TensorRT preparation: inference libraries ready" in diagnostic


def test_helper_dumps_repeated_stacks_during_a_blocked_inference_import(tmp_path):
    fixture = Path(__file__).parents[2] / "support/tensorrt_stalled_import.py"
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    log = tmp_path / "build.log"
    with (
        log.open("w", encoding="utf-8") as output,
        subprocess.Popen(
            [sys.executable, "-u", str(fixture), str(request)],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
        ) as process,
    ):
        try:
            deadline = monotonic() + 10
            diagnostic = ""
            while monotonic() < deadline:
                diagnostic = log.read_text(encoding="utf-8")
                if diagnostic.count("Timeout (") >= 2:
                    break
                assert process.poll() is None, diagnostic
                Event().wait(0.01)
            assert diagnostic.count("Timeout (") >= 2, diagnostic
            assert "TensorRT preparation: importing NumPy" in diagnostic
            assert "tensorrt_stalled_import.py" in diagnostic
            assert "in find_spec" in diagnostic
            assert "in build_and_test" in diagnostic
            assert process.poll() is None  # Diagnostics do not abort a slow build.
            process.stdin.close()
            assert process.wait(timeout=10) == 1
        finally:
            if process.poll() is None:
                process.kill()


@pytest.mark.parametrize("failure", ["builder", "engine load"])
def test_automatic_engine_failure_keeps_the_original_torch_model(
    tmp_path, gpu_builder, monkeypatch, failure
):
    from ultralytics.engine.predictor import BasePredictor

    YOLO("yolo26n.yaml").save(gpu_builder.source)
    if failure == "builder":
        monkeypatch.setenv("TENSORRT_TEST_MODE", "failed")
    else:
        setup_model = BasePredictor.setup_model

        def setup(self, model=None, verbose=True):
            if isinstance(model, str) and model.endswith(".engine"):
                raise RuntimeError("TensorRT could not deserialize this engine")
            return setup_model(self, model, verbose)

        monkeypatch.setattr(BasePredictor, "setup_model", setup)
    config = YoloConfig(model=str(gpu_builder.source), imgsz=64)
    cache = tmp_path / "cache"
    prepare_engine(config, OnnxConfig(), 1, InferenceOptions(), cache, lambda _: None)
    for _ in range(2):
        with open_detector(
            config,
            OnnxConfig(),
            ("camera",),
            "cuda",
            InferenceOptions(),
            cache,
            engines=EnginePreparation(cache),
        ) as detector:
            assert detector.model.predictor.model.format == "pt"
            assert detector.model.ckpt_path == str(gpu_builder.source)
    assert len(gpu_builder.commands) == 1


@pytest.mark.parametrize("invalid", [False, True])
def test_gpu_smoke_test_checks_dynamic_shapes_and_rejects_nonfinite_results(
    tmp_path, monkeypatch, invalid
):
    from ultralytics.engine.results import Results

    predictions, exports = [], []

    class Model:
        def __init__(self, path, task):
            self.path = Path(path)

        def export(self, **arguments):
            exports.append(arguments)
            return self.path.with_suffix(".engine")

        def predict(self, images, **arguments):
            predictions.append((len(images), images[0].shape, arguments))
            box = torch.tensor([[0, 0, 1, 1, float("nan") if invalid else 0.5, 0]])
            return [
                Results(image, path=str(self.path), names={0: "cow"}, boxes=box)
                for image in images
            ]

    monkeypatch.setattr("ultralytics.YOLO", Model)
    request = {
        "checkpoint": str(tmp_path / "model.pt"),
        "task": "detect",
        "export": {
            "imgsz": 64,
            "batch": 3,
            "format": "engine",
            "dynamic": True,
            "quantize": 16,
            "device": 0,
        },
    }
    if invalid:
        with pytest.raises(RuntimeError, match="invalid detection results"):
            build_and_test(request)
    else:
        build_and_test(request)
        assert exports == [request["export"]]
        assert [(count, shape) for count, shape, _ in predictions] == [
            (1, (32, 64, 3)),
            (1, (64, 64, 3)),
            (3, (32, 64, 3)),
            (3, (64, 64, 3)),
        ]
        assert all(arguments["device"] == 0 for _, _, arguments in predictions)


@pytest.mark.skipif(
    not torch.cuda.is_available() or importlib.util.find_spec("tensorrt") is None,
    reason="Requires CUDA and the downloaded TensorRT runtime",
)
def test_real_sdk_builds_and_runs_dynamic_engine_in_helper(tmp_path):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo26n.yaml").save(checkpoint)
    engine = prepare_engine(
        YoloConfig(model=str(checkpoint), imgsz=64),
        OnnxConfig(),
        2,
        InferenceOptions(half=True),
        tmp_path / "prepared",
        lambda _: None,
    )
    assert engine is not None, (
        "TensorRT preparation must succeed on the qualified GPU runner"
    )
    model = YOLO(str(engine))
    for shape in ((32, 64), (64, 32), (64, 64)):
        results = model.predict(
            [np.zeros((*shape, 3), dtype=np.uint8)] * 2,
            imgsz=64,
            device=0,
            verbose=False,
        )
        assert len(results) == 2
        assert all(
            np.isfinite(result.boxes.cpu().numpy().data).all() for result in results
        )


def test_a_tensorrt_preference_without_a_gpu_detects_without_it(
    tmp_path, gpu_builder, monkeypatch, caplog
):
    monkeypatch.setattr(bootstrap, "TYPE", "cuda")
    monkeypatch.setattr(prepared_engines, "gpu_available", lambda: False)
    monkeypatch.setattr(
        bootstrap,
        "inference_runtime",
        lambda *args: nullcontext(InferenceOptions()),
    )
    YOLO("yolo26n.yaml").save(gpu_builder.source)
    assert cv2.imwrite(str(tmp_path / "input.png"), np.zeros((64, 64, 3), np.uint8))
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "input.png"},
                    "yolo": {"model": str(gpu_builder.source), "imgsz": 64},
                }
            ]
        }
    )
    results = bootstrap.run_application(
        config, tmp_path, tmp_path, prefer_tensorrt=True
    )
    assert len(results) == 1
    assert gpu_builder.processes == []
    assert "no NVIDIA GPU is available" in caplog.text
