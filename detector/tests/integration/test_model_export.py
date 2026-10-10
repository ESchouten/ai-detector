"""Real SDK exports: topology, Torch-weight lifetime, and the prepared ONNX cache."""

import gc
from datetime import datetime
from weakref import ref

import numpy as np
import onnx
import onnxruntime
from ultralytics import YOLO

from aidetector.adapters.inference.onnx import (
    InferenceOptions,
    ModelRequirements,
    inference_runtime,
)
from aidetector.adapters.inference.prepared_models import prepare_onnx
from aidetector.adapters.inference.yolo import open_detector
from aidetector.configuration import Config, OnnxConfig, YoloConfig
from aidetector.domain.models import Frame


def test_real_yolo26_fp16_cpu_export_is_valid_and_runs_dynamic_batches(tmp_path):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo26n.yaml").save(checkpoint)
    config = YoloConfig(model=str(checkpoint), imgsz=64)
    options = InferenceOptions(half=True)
    cache = tmp_path / "cache"
    exported = prepare_onnx(config, OnnxConfig(opset=20), 1, options, cache)
    onnx.checker.check_model(str(exported))
    graph = onnx.load(exported)
    assert any(
        tensor.data_type == onnx.TensorProto.FLOAT16
        for tensor in graph.graph.initializer
    )
    assert graph.metadata_props
    session = onnxruntime.InferenceSession(
        str(exported), providers=["CPUExecutionProvider"]
    )
    for batch in (1, 2):
        result = session.run(
            None, {"images": np.zeros((batch, 3, 64, 64), dtype=np.float32)}
        )
        assert result[0].shape[0] == batch
        assert np.isfinite(result[0]).all()
    assert prepare_onnx(config, OnnxConfig(opset=20), 1, options, cache) == exported


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


def test_real_checkpoint_export_releases_weights_and_runs_the_onnx_model(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo11n.yaml").save(checkpoint)
    created = []

    def record_model(*args, **kwargs):
        model = YOLO(*args, **kwargs)
        created.append(ref(model))
        return model

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", record_model)
    config = Config.model_validate(
        {
            "onnx": {"provider": "CPUExecutionProvider"},
            "detectors": [
                {
                    "detection": {"source": "0"},
                    "yolo": {"model": str(checkpoint), "imgsz": 64},
                }
            ],
        }
    )
    settings = config.detectors[0].yolo
    models = (ModelRequirements(str(checkpoint), image_size=64, batch_size=1),)
    with (
        inference_runtime(config.onnx, models, "default") as options,
        open_detector(settings, config.onnx, ("0",), "default", options) as detector,
    ):
        model = detector.model
        gc.collect()
        assert len(created) == 2
        assert created[0]() is None
        assert created[1]() is model
        frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
        [observation] = detector.detect({"0": (frame,)})["0"]
        assert observation.date == frame.date
        assert observation.image is frame.image
    assert model.predictor is None
