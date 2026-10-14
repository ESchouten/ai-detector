import os
import pathlib
import sys
from datetime import datetime
from types import SimpleNamespace

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
from aidetector.configuration import OnnxConfig, YoloConfig
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
                session=SimpleNamespace(get_providers=lambda: ["CPUExecutionProvider"]),
                use_io_binding=False,
            )

    class Model:
        def __init__(self, path, task):
            self.model = path
            self.names = {0: "cow"}
            self.overrides = {}
            self.callbacks = {}
            self.predictor = None
            created.append(path)

        def export(self, **options):
            exports.append(options)
            return "converted.onnx"

        def _smart_load(self, name):
            assert name == "predictor"
            return Predictor

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", Model)
    return SimpleNamespace(created=created, exports=exports)


def test_conversion_passes_the_onnx_format_and_settings_to_the_sdk(model_sdk):
    with open_detector(
        YoloConfig(model="weights.pt", imgsz=128),
        OnnxConfig(opset=19),
        ("camera-1", "camera-2"),
        "default",
        InferenceOptions(half=True),
    ):
        assert model_sdk.exports == [
            {
                "format": "onnx",
                "batch": 2,
                "dynamic": True,
                "quantize": 16,
                "imgsz": 128,
                "simplify": True,
                "opset": 19,
                "nms": False,
            }
        ]


def test_core_ml_model_is_prepared_once_and_loaded_instead_of_the_checkpoint(
    model_sdk, monkeypatch, tmp_path
):
    prepared = []

    def prepare_core_ml(config, cache, report_status):
        prepared.append((config.model, cache))
        return tmp_path / "model.mlpackage"

    monkeypatch.setattr(
        "aidetector.adapters.inference.prepared_models.prepare_core_ml",
        prepare_core_ml,
    )
    cache = tmp_path / "prepared"
    with open_detector(
        YoloConfig(model="weights.pt"),
        OnnxConfig(),
        ("camera-1", "camera-2"),
        "default",
        InferenceOptions(core_ml=True),
        cache_directory=cache,
    ) as detector:
        assert prepared == [("weights.pt", cache)]
        assert model_sdk.created == [str(tmp_path / "model.mlpackage")]
        assert model_sdk.exports == []
        # The model itself is half precision; the SDK picks Core ML's processors.
        assert detector.model.predictor.args.device is None
        assert detector.model.predictor.args.quantize is None


def test_core_ml_without_a_cache_passes_its_settings_to_the_sdk(model_sdk):
    with open_detector(
        YoloConfig(model="weights.pt", imgsz=320),
        OnnxConfig(),
        ("camera-1", "camera-2"),
        "default",
        InferenceOptions(core_ml=True),
    ):
        assert model_sdk.exports == [
            {"format": "coreml", "batch": 1, "quantize": 16, "imgsz": 320, "nms": False}
        ]


@pytest.mark.parametrize("suffix", ["onnx", "engine"])
def test_exported_model_is_not_converted_for_core_ml(model_sdk, suffix):
    with open_detector(
        YoloConfig(model=f"weights.{suffix}"),
        OnnxConfig(),
        ("0",),
        "default",
        InferenceOptions(core_ml=True),
    ) as detector:
        assert detector.model.model == f"weights.{suffix}"
        assert detector.model.predictor.args.device is None
        assert detector.model.predictor.args.quantize is None
        assert model_sdk.exports == []


@pytest.mark.skipif(sys.platform != "darwin", reason="Core ML runs on a Mac")
@pytest.mark.parametrize("tracking", [False, True])
def test_real_checkpoint_runs_on_core_ml_on_a_mac(tmp_path, tracking):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo26n.yaml").save(checkpoint)
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
        assert options.core_ml is True
        predictor = detector.model.predictor
        assert predictor.model.format == "coreml"
        frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
        [observation] = detector.detect({"0": (frame,)})["0"]
        assert detector.model.predictor is predictor
        assert observation.date == frame.date
        assert observation.image is frame.image
        assert [path.name for path in cache.glob("*/*")] == ["model.mlpackage"]
    assert detector.model.predictor is None


@pytest.mark.parametrize("half", [False, True])
def test_real_native_model_uses_the_requested_precision_without_downloading_weights(
    tmp_path, half
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
        assert model.predictor.args.quantize == (16 if half else None)
        # The SDK keeps full precision on a processor, whatever was asked.
        fp16 = half and torch.cuda.is_available()
        assert model.predictor.model.fp16 is fp16
        assert next(model.model.parameters()).dtype is (
            torch.float16 if fp16 else torch.float32
        )
    assert model.predictor is None


def test_real_model_with_a_head_without_suppression_keeps_using_it(tmp_path):
    checkpoint = tmp_path / "fixture.pt"
    YOLO("yolo26n.yaml").save(checkpoint)
    with open_detector(
        YoloConfig(model=str(checkpoint), imgsz=64),
        OnnxConfig(),
        ("0",),
        "cuda",
        InferenceOptions(),
    ) as detector:
        predictor = detector.model.predictor
        assert predictor.model.end2end is True
        frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
        detector.detect({"0": (frame,)})
        # Left to itself the SDK builds a second backend with the other head, whose
        # confidences differ from the ones a model's thresholds were chosen with.
        assert detector.model.predictor is predictor
        assert detector.model.predictor.model.end2end is True


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
