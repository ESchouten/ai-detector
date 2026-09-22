from datetime import datetime

import numpy as np
import pytest
from ultralytics import YOLO

from aidetector.adapters.inference.onnx import (
    InferenceOptions,
    ModelRequirements,
    inference_runtime,
)
from aidetector.adapters.inference.prepared_models import prepare_onnx
from aidetector.adapters.inference.yolo import open_detector
from aidetector.configuration import OnnxConfig, YoloConfig
from aidetector.domain.models import Frame
from tests.support.onnx_model import write_detection_model


@pytest.fixture
def prepared_checkpoint(tmp_path, monkeypatch):
    source = tmp_path / "input.pt"
    source.write_bytes(b"checkpoint-one")
    calls = []

    class Model:
        def __init__(self, checkpoint, task):
            from pathlib import Path

            self.path = Path(checkpoint)
            assert self.path.read_bytes().startswith(b"checkpoint-")

        def export(self, **arguments):
            calls.append(arguments)
            output = self.path.with_suffix(".onnx")
            write_detection_model(output)
            return str(output)

    monkeypatch.setattr("aidetector.adapters.inference.prepared_models.YOLO", Model)
    return source, calls


def test_identical_checkpoint_reuses_prepared_model_without_export_or_source_mutation(
    tmp_path, prepared_checkpoint
):
    source, calls = prepared_checkpoint
    original = source.read_bytes()
    config = YoloConfig(model=str(source), imgsz=64)
    progress = []
    first = prepare_onnx(
        config, OnnxConfig(), 1, InferenceOptions(), tmp_path / "cache", progress.append
    )
    assert len(progress) == 1
    assert "Preparing the model" in progress[0].message
    progress.clear()
    second = prepare_onnx(
        config, OnnxConfig(), 1, InferenceOptions(), tmp_path / "cache", progress.append
    )
    assert progress == []
    assert first == second
    assert len(calls) == 1
    assert first.is_file()
    assert source.read_bytes() == original
    assert not source.with_suffix(".onnx").exists()
    assert not list((tmp_path / "cache").glob("preparing-*"))
    assert not first.with_suffix(".pt").exists()


def test_stock_download_failure_is_reported_and_not_misclassified_as_ready(
    tmp_path, monkeypatch
):
    def unavailable(_model):
        raise ConnectionError("Offline")

    monkeypatch.setattr(
        "aidetector.adapters.inference.prepared_models.attempt_download_asset",
        unavailable,
    )
    progress = []
    with pytest.raises(ConnectionError):
        prepare_onnx(
            YoloConfig(model="yolo11n.pt"),
            OnnxConfig(),
            1,
            InferenceOptions(),
            tmp_path / "cache",
            progress.append,
        )
    assert [event.kind for event in progress] == ["preparing", "preparation_failed"]
    assert "internet" in progress[-1].message
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    "change", ["weights", "size", "batch", "precision", "opset", "task", "sdk"]
)
def test_changed_model_or_conversion_contract_never_reuses_an_incompatible_export(
    tmp_path, prepared_checkpoint, monkeypatch, change
):
    source, calls = prepared_checkpoint
    config = YoloConfig(model=str(source), imgsz=64)
    onnx = OnnxConfig()
    options = InferenceOptions()
    cache = tmp_path / "cache"
    first = prepare_onnx(config, onnx, 1, options, cache)
    batch = 1
    if change == "weights":
        source.write_bytes(b"checkpoint-two")
    elif change == "size":
        config = config.model_copy(update={"imgsz": 128})
    elif change == "batch":
        batch = 2
    elif change == "precision":
        options = InferenceOptions(half=True)
    elif change == "opset":
        onnx = OnnxConfig(opset=19)
    elif change == "task":
        config = config.model_copy(update={"task": "segment"})
    else:
        monkeypatch.setattr(
            "aidetector.adapters.inference.prepared_models.ultralytics.__version__",
            "future-version",
        )
    second = prepare_onnx(config, onnx, batch, options, cache)
    assert first != second
    assert first.is_file() and second.is_file()
    assert len(calls) == 2


def test_interrupted_export_is_not_published_and_can_be_retried(
    tmp_path, prepared_checkpoint, monkeypatch
):
    source, calls = prepared_checkpoint
    from aidetector.adapters.inference import prepared_models

    export = prepared_models.YOLO.export

    def fail(self, **arguments):
        self.path.with_suffix(".onnx").write_bytes(b"partial")
        raise OSError("Disk write interrupted")

    monkeypatch.setattr(prepared_models.YOLO, "export", fail)
    cache = tmp_path / "cache"
    config = YoloConfig(model=str(source))
    with pytest.raises(OSError, match="interrupted"):
        prepare_onnx(config, OnnxConfig(), 1, InferenceOptions(), cache)
    assert list(cache.iterdir()) == []
    monkeypatch.setattr(prepared_models.YOLO, "export", export)
    assert prepare_onnx(config, OnnxConfig(), 1, InferenceOptions(), cache).is_file()
    assert len(calls) == 1


def test_real_torch_checkpoint_is_exported_once_and_cached_onnx_runs_on_reopen(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo11n.yaml").save(checkpoint)
    config = YoloConfig(model=str(checkpoint), imgsz=64)
    onnx = OnnxConfig(provider="CPUExecutionProvider")
    requirements = (ModelRequirements(str(checkpoint), image_size=64, batch_size=1),)
    frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
    exports = []
    original_export = YOLO.export

    def export(self, **arguments):
        exports.append(arguments)
        return original_export(self, **arguments)

    monkeypatch.setattr(YOLO, "export", export)
    for _ in range(2):
        with inference_runtime(onnx, requirements, "default") as options:
            with open_detector(
                config, onnx, ("camera",), "default", options, tmp_path / "cache"
            ) as detector:
                observations = detector.detect({"camera": (frame,)})
                assert observations["camera"][0].date == frame.date
                assert detector.model.model.endswith(".onnx")
    assert len(exports) == 1
    assert not checkpoint.with_suffix(".onnx").exists()
