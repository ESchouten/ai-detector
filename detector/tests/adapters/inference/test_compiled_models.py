import logging
import os
from pathlib import Path
from threading import Event

import onnxruntime as ort
import pytest

from aidetector.adapters.inference import compiled_models
from aidetector.adapters.inference.compiled_models import (
    Accelerator,
    CompiledModels,
    picture_heights,
    run_first_batches,
)
from tests.support.onnx_model import write_detection_model

SOURCE = Path(__file__).resolve().parents[3] / "src"
CPU = next(device for device in ort.get_ep_devices())


@pytest.fixture
def model(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("PYTHONPATH", str(SOURCE))
    caplog.set_level(logging.INFO)
    path = tmp_path / "model.onnx"
    write_detection_model(path)
    return path


def compiled_models_for(cache, ready):
    return CompiledModels(
        cache,
        (Accelerator(CPU.ep_name, str(CPU.device.type), {}),),
        {},
        ort.__version__,
        (96,),
        2,
        lambda event: ready.set() if event.kind == "models_ready" else None,
    )


def test_helper_tests_a_model_the_provider_does_not_compile_and_keeps_it(
    model, tmp_path, caplog
):
    ready = Event()
    models = compiled_models_for(tmp_path / "compiled", ready)
    try:
        assert models.model(model) is None
        assert ready.wait(120), caplog.text
    finally:
        models.close()
    [destination] = (tmp_path / "compiled").iterdir()
    log = (destination / "build.log").read_text()
    assert "did not compile the model; testing it as is" in log
    assert "Test: batch=2; image=64x96" in log
    assert not (destination / "failure.txt").exists()
    assert not (destination / "model").exists()
    assert compiled_models_for(tmp_path / "compiled", Event()).model(model) == model


def test_failed_compilation_is_deferred_for_a_day(model, tmp_path, caplog):
    ready = Event()
    models = compiled_models_for(tmp_path / "compiled", ready)
    models.reject(model, "the accelerator stopped responding")
    assert models.model(model) is None
    models.close()
    assert not ready.is_set()
    assert "compilation deferred" in caplog.text
    assert "stopped responding" in caplog.text
    [destination] = (tmp_path / "compiled").iterdir()
    os.utime(destination / "failure.txt", (0, 0))
    models = compiled_models_for(tmp_path / "compiled", ready)
    try:
        assert models.model(model) is None
        assert ready.wait(120), caplog.text
    finally:
        models.close()


def test_slow_first_batch_rejects_the_accelerator(model, monkeypatch):
    monkeypatch.setattr(compiled_models, "FIRST_RUN_LIMIT", 0.0)
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    with pytest.raises(RuntimeError, match="first batch of 1 at 64x64"):
        run_first_batches(session, [64], 2)


def test_cancelled_compilation_is_retried_at_the_next_start(
    model, tmp_path, monkeypatch
):
    started = Event()

    def compile_model(request, log_path, stop_requested):
        started.set()
        stop_requested.wait()
        raise KeyboardInterrupt

    monkeypatch.setattr(compiled_models, "run_compilation", compile_model)
    models = compiled_models_for(tmp_path / "compiled", Event())
    try:
        assert models.model(model) is None
        assert started.wait(10)
    finally:
        models.close()
    [destination] = (tmp_path / "compiled").iterdir()
    assert not (destination / "failure.txt").exists()
    assert not (destination / "ready.json").exists()


@pytest.mark.parametrize(
    ("size", "heights"),
    [(640, [384, 480, 640]), (64, [64]), (96, [64, 96]), (320, [192, 256, 320])],
)
def test_tested_pictures_cover_square_and_camera_shapes(size, heights):
    assert picture_heights(size) == heights
