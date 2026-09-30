import importlib.util
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from filelock import FileLock
from ultralytics import YOLO

from aidetector.adapters.inference import prepared_engines
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.adapters.inference.prepared_engines import prepare_engine, reject_engine
from aidetector.adapters.inference.tensorrt_worker import build_and_test
from aidetector.adapters.inference.yolo import open_detector
from aidetector.configuration import OnnxConfig, YoloConfig


@pytest.fixture
def gpu_builder(tmp_path, monkeypatch):
    source = tmp_path / "input.pt"
    source.write_bytes(b"checkpoint")
    gpu = SimpleNamespace(name="RTX fixture", major=8, minor=6, total_memory=8 << 30)
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda _index: gpu)
    monkeypatch.setattr(prepared_engines, "version", lambda _name: "1.0")
    monkeypatch.setenv("AI_DETECTOR_NVIDIA_DRIVER", "580.88")
    processes, commands = [], []
    popen = subprocess.Popen
    fixture = Path(__file__).parents[2] / "support/tensorrt_process.py"

    def start(command, **kwargs):
        commands.append(command)
        assert command[-2] == "--prepare-tensorrt"
        process = popen([sys.executable, "-u", str(fixture), command[-1]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    return SimpleNamespace(
        source=source, gpu=gpu, commands=commands, processes=processes
    )


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
    assert "GPU builder fixture: ready" in (first.parent / "build.log").read_text()


@pytest.mark.parametrize(
    "change", ["weights", "size", "batch", "precision", "gpu", "driver", "runtime"]
)
def test_engine_cache_is_specific_to_weights_settings_gpu_and_runtime(
    tmp_path, gpu_builder, monkeypatch, change
):
    config = YoloConfig(model=str(gpu_builder.source), imgsz=64)
    options = InferenceOptions(half=True)
    cache = tmp_path / "cache"
    first = prepare_engine(config, OnnxConfig(), 1, options, cache, lambda _: None)
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
    second = prepare_engine(config, OnnxConfig(), batch, options, cache, lambda _: None)
    assert first is not None and second is not None and first != second
    assert first.is_file() and second.is_file()
    assert len(gpu_builder.commands) == 2


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
    for _ in range(2):
        with open_detector(
            YoloConfig(model=str(gpu_builder.source), imgsz=64),
            OnnxConfig(),
            ("camera",),
            "cuda",
            InferenceOptions(),
            tmp_path / "cache",
            prefer_tensorrt=True,
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
