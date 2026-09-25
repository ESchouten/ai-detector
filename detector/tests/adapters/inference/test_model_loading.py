import gc
import os
import pathlib
import sys
from datetime import datetime
from types import SimpleNamespace
from weakref import ref

import numpy as np
import pytest
import torch
from ultralytics import YOLO
from ultralytics.cfg import get_cfg

from aidetector.adapters.inference.onnx import (
    InferenceOptions,
    ModelRequirements,
    inference_runtime,
)
from aidetector.adapters.inference.yolo import open_detector
from aidetector.configuration import Config, OnnxConfig, YoloConfig
from aidetector.domain.models import Frame


@pytest.fixture
def model_sdk(monkeypatch):
    created, exports = [], []

    class Predictor:
        def __init__(self, overrides, _callbacks):
            self.args = get_cfg(overrides=overrides)

        def setup_model(self, model, verbose):
            self.model = SimpleNamespace(
                format=pathlib.Path(model).suffix.lstrip("."),
                device=self.args.device or "cpu",
                fp16=self.args.quantize == 16,
            )

    class Model:
        def __init__(self, path, task):
            self.model = path
            self.names = {0: "cow"}
            self.overrides = {}
            self.callbacks = {}
            self.predictor = None
            created.append(ref(self))

        def export(self, **options):
            exports.append(options)
            return "converted.onnx"

        def _smart_load(self, name):
            assert name == "predictor"
            return Predictor

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", Model)
    return SimpleNamespace(created=created, exports=exports)


def test_export_model_is_released_before_inference_starts(model_sdk):
    with open_detector(
        YoloConfig(model="weights.pt"),
        OnnxConfig(),
        ("0", "1"),
        "default",
        InferenceOptions(),
    ) as detector:
        model = detector.model
        assert model.model == "converted.onnx"
        assert model_sdk.created[0]() is None, "Export-only weights are still retained"
        assert model_sdk.created[1]() is model
        assert model_sdk.exports[0]["batch"] == 2
    assert model.predictor is None


@pytest.mark.parametrize(
    "build_type, model_format", [("default", "onnx"), ("tensorrt", "engine")]
)
def test_conversion_passes_the_selected_format_and_settings_to_the_sdk(
    model_sdk, build_type, model_format
):
    with open_detector(
        YoloConfig(model="weights.pt", imgsz=128),
        OnnxConfig(opset=19),
        ("camera-1", "camera-2"),
        build_type,
        InferenceOptions(half=True),
    ):
        assert model_sdk.exports == [
            {
                "format": model_format,
                "batch": 2,
                "dynamic": True,
                "quantize": 16,
                "imgsz": 128,
                "simplify": True,
                "opset": 19,
            }
        ]


@pytest.mark.parametrize("half", [False, True])
def test_native_model_precision_is_selected_when_the_predictor_is_created(
    model_sdk, half
):
    with open_detector(
        YoloConfig(model="weights.pt"),
        OnnxConfig(),
        ("0",),
        "cuda",
        InferenceOptions(half=half),
    ) as detector:
        model = detector.model
        assert model.predictor.args.quantize == (16 if half else None)
        assert model_sdk.exports == []
    assert model.predictor is None


def test_native_mps_model_skips_export_and_uses_fp16(model_sdk, tmp_path):
    cache = tmp_path / "prepared"
    with open_detector(
        YoloConfig(model="weights.pt"),
        OnnxConfig(),
        ("0",),
        "default",
        InferenceOptions(native_mps=True),
        cache_directory=cache,
    ) as detector:
        assert detector.model.model == "weights.pt"
        assert detector.model.predictor.args.device == "mps"
        assert detector.model.predictor.args.quantize == 16
        assert len(model_sdk.created) == 1
        assert model_sdk.exports == []
        assert not cache.exists()
    assert detector.model.predictor is None


@pytest.mark.parametrize("suffix", ["onnx", "engine"])
def test_exported_model_is_not_redirected_to_mps(model_sdk, suffix):
    with open_detector(
        YoloConfig(model=f"weights.{suffix}"),
        OnnxConfig(),
        ("0",),
        "default",
        InferenceOptions(native_mps=True),
    ) as detector:
        assert detector.model.model == f"weights.{suffix}"
        assert detector.model.predictor.args.device is None
        assert detector.model.predictor.args.quantize is None
        assert model_sdk.exports == []


def test_failed_mps_model_load_remains_a_visible_failure(monkeypatch):
    def failed_load(*args, **kwargs):
        raise RuntimeError("Broken checkpoint")

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", failed_load)
    with (
        pytest.raises(RuntimeError, match="Broken checkpoint"),
        open_detector(
            YoloConfig(model="broken.pt"),
            OnnxConfig(),
            ("0",),
            "default",
            InferenceOptions(native_mps=True),
        ),
    ):
        pytest.fail("A model error must not trigger another backend")


@pytest.mark.skipif(
    sys.platform != "darwin" or not torch.backends.mps.is_available(),
    reason="Requires an available Apple MPS device",
)
@pytest.mark.parametrize("tracking", [False, True])
def test_real_mps_checkpoint_inference_without_export_or_download(tmp_path, tracking):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo11n.yaml").save(checkpoint)
    settings = YoloConfig(model=str(checkpoint), imgsz=64, tracking=tracking)
    onnx = OnnxConfig()
    models = (ModelRequirements(str(checkpoint), image_size=64, batch_size=1),)
    cache = tmp_path / "prepared"
    with (
        inference_runtime(onnx, models, "default") as options,
        open_detector(
            settings, onnx, ("0",), "default", options, cache_directory=cache
        ) as detector,
    ):
        assert options.native_mps is True
        predictor = detector.model.predictor
        backend = predictor.model
        assert backend.device.type == "mps"
        assert backend.fp16 is True
        frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
        [observation] = detector.detect({"0": (frame,)})["0"]
        assert detector.model.predictor is predictor
        assert detector.model.predictor.model.device.type == "mps"
        assert detector.model.predictor.model.fp16 is True
        assert observation.date == frame.date
        assert observation.image is frame.image
        assert not cache.exists()
        assert list(tmp_path.glob("*.onnx")) == []
    assert detector.model.predictor is None


@pytest.mark.parametrize("half, dtype", [(False, torch.float32), (True, torch.float16)])
def test_real_native_model_uses_the_requested_precision_without_downloading_weights(
    tmp_path, half, dtype
):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo11n.yaml").save(checkpoint)
    with open_detector(
        YoloConfig(model=str(checkpoint), imgsz=64),
        OnnxConfig(),
        ("0",),
        "cuda",
        InferenceOptions(half=half),
    ) as detector:
        model = detector.model
        assert model.predictor.model.fp16 is half
        assert next(model.model.parameters()).dtype is dtype
    assert model.predictor is None


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


def test_sdk_loads_a_foreign_checkpoint_path_and_pathlib_is_restored(tmp_path):
    windows, posix = pathlib.WindowsPath, pathlib.PosixPath
    foreign_path = posix if os.name == "nt" else windows

    class TrainingPath:
        def __reduce__(self):
            return foreign_path, ("training/weights.pt",)

    checkpoint = tmp_path / "foreign.pt"
    torch.save(
        {"model": YOLO("yolo11n.yaml").model, "training_path": TrainingPath()},
        checkpoint,
    )
    with pytest.raises(NotImplementedError):
        torch.load(checkpoint, weights_only=False)

    with open_detector(
        YoloConfig(model=str(checkpoint), imgsz=64),
        OnnxConfig(),
        ("0",),
        "cuda",
        InferenceOptions(),
    ) as detector:
        assert isinstance(detector.model.ckpt["training_path"], pathlib.Path)
        assert pathlib.WindowsPath is windows
        assert pathlib.PosixPath is posix
    assert detector.model.predictor is None


def test_failed_checkpoint_load_restores_both_path_classes(monkeypatch):
    windows, posix = pathlib.WindowsPath, pathlib.PosixPath

    def failed_load(*args, **kwargs):
        # Both platform branches of the SDK alter a pathlib class.
        pathlib.WindowsPath, pathlib.PosixPath = posix, windows
        raise OSError("Unreadable checkpoint")

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", failed_load)
    with (
        pytest.raises(OSError, match="Unreadable checkpoint"),
        open_detector(
            YoloConfig(model="broken.pt"),
            OnnxConfig(),
            ("0",),
            "cuda",
            InferenceOptions(),
        ),
    ):
        pytest.fail("The broken checkpoint must fail startup")
    assert pathlib.WindowsPath is windows
    assert pathlib.PosixPath is posix
