import gc
from datetime import datetime, timedelta
from weakref import ref

import numpy as np
import onnxruntime as ort
import pytest

from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.inference.yolo import open_detector
from aidetector.bootstrap import run_application
from aidetector.configuration import Config
from aidetector.domain.models import Frame
from tests.support.onnx_model import write_detection_model


@pytest.mark.parametrize("tracking", [False, True])
def test_real_onnx_yolo_batching_tracking_and_session_lifetime(
    tmp_path, monkeypatch, tracking
):
    path = tmp_path / "detector.onnx"
    write_detection_model(path)
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": ["0", "1"]},
                    "yolo": {
                        "model": str(path),
                        "imgsz": 64,
                        "confidence": {"cow": 0.5},
                        "tracking": tracking,
                    },
                }
            ],
            "onnx": {"provider": "CPUExecutionProvider"},
        }
    )
    original = ort.InferenceSession
    sessions = []

    def count_sessions(*args, **kwargs):
        session = original(*args, **kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(ort, "InferenceSession", count_sessions)
    frame = Frame(datetime(2026, 1, 1), np.zeros((64, 64, 3), dtype=np.uint8))
    image_ref = ref(frame.image)
    later = Frame(frame.date + timedelta(seconds=1), frame.image)
    settings = config.detectors[0].yolo
    models = (ModelRequirements(str(path), image_size=64, batch_size=2),)
    with inference_runtime(config.onnx, models, "default") as options:
        with open_detector(
            settings, config.onnx, ("0", "1"), "default", options
        ) as detector:
            first = detector.detect({"0": (frame,), "1": (frame,)})
            second = detector.detect({"1": (later,)})
            assert set(first) == {"0", "1"}
            assert set(second) == {"1"}
            assert first["0"][0].confidence == {"cow": pytest.approx(0.9)}
            assert second["1"][0].date == later.date
            assert second["1"][0].boxes[0].x1 == 10
            assert len(sessions) == 1
            del frame, later, first, second
            gc.collect()
            assert image_ref() is not None
        assert detector.model.predictor is None
        gc.collect()
        assert image_ref() is None
    assert ort.InferenceSession is count_sessions


def test_failed_detector_startup_releases_the_loaded_predictor(tmp_path, monkeypatch):
    import cv2
    from ultralytics import YOLO

    model_path = tmp_path / "model.onnx"
    write_detection_model(model_path)
    assert cv2.imwrite(
        str(tmp_path / "input.png"), np.zeros((64, 64, 3), dtype=np.uint8)
    )
    models = []

    def record_model(*args, **kwargs):
        model = YOLO(*args, **kwargs)
        models.append(model)
        return model

    monkeypatch.setattr("aidetector.adapters.inference.yolo.YOLO", record_model)
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "input.png"},
                    "yolo": {
                        "model": str(model_path),
                        "confidence": {"unknown": 0.5},
                        "imgsz": 64,
                    },
                }
            ],
            "onnx": {"provider": "CPUExecutionProvider"},
        }
    )
    with pytest.raises(ValueError, match="Unknown YOLO classes"):
        run_application(config, tmp_path, tmp_path)
    assert len(models) == 1
    assert models[0].predictor is None
