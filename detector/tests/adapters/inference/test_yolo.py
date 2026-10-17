import gc
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from weakref import ref

import cv2
import numpy as np
import onnxruntime as ort
import pytest
from ultralytics import YOLO
from ultralytics.engine.results import Results

from aidetector.adapters.inference import yolo
from aidetector.adapters.inference.onnx import (
    InferenceOptions,
    ModelRequirements,
    inference_runtime,
)
from aidetector.adapters.inference.yolo import (
    InMemoryStreamBatch,
    YoloDetector,
    map_observations,
    open_detector,
    resolve_classes,
)
from aidetector.bootstrap import run_application
from aidetector.configuration import Config, YoloConfig
from aidetector.domain.models import Frame
from tests.support.onnx_model import write_detection_model


def result(boxes=(), *, tracking=False):
    return Results(
        orig_img=np.zeros((64, 64, 3), dtype=np.uint8),
        path="frame.jpg",
        names={0: "cow", 1: "horse"},
        boxes=np.asarray(boxes, dtype=np.float32).reshape(-1, 7 if tracking else 6),
    )


def frame(second=0, color=0):
    return Frame(
        datetime(2026, 1, 1) + timedelta(seconds=second),
        np.full((64, 64, 3), color, dtype=np.uint8),
    )


def test_real_ultralytics_results_are_mapped_at_the_boundary():
    observations = map_observations(
        result(
            [
                [10, 20, 30, 40, 0.8, 0],
                [35, 20, 50, 40, 0.6, 0],
                [1, 2, 3, 4, 0.6, 1],
            ]
        ),
        (frame(0), frame(1)),
        {0: ("cow", 0.5), 1: ("horse", 0.7)},
    )
    assert observations[0].confidence == {}
    assert observations[1].confidence["cow"] == pytest.approx(0.8)
    assert len(observations[1].boxes) == 2
    assert observations[1].boxes[0].label == "cow"
    assert observations[1].boxes[0].track_id is None


def test_tracker_ids_are_preserved_without_changing_context_frame_scores():
    observations = map_observations(
        result([[10, 20, 30, 40, 7, 0.8, 0]], tracking=True),
        (frame(0), frame(1)),
        {0: ("cow", 0.5)},
    )
    assert observations[0].confidence == {}
    assert observations[1].confidence == {"cow": pytest.approx(0.8)}
    assert observations[0].boxes == observations[1].boxes
    assert observations[1].boxes[0].track_id == 7


def test_no_boxes_still_produce_unscored_observations_for_trailing_footage():
    observations = map_observations(result(), (frame(0), frame(1)), {0: ("cow", 0.5)})
    assert len(observations) == 2
    assert all(not item.confidence and not item.boxes for item in observations)


class Model:
    names = {0: "cow", 1: "horse"}

    def __init__(self):
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [result() for _ in kwargs["source"]]

    def track(self, **kwargs):
        self.calls.append(kwargs)
        return [result([[1, 2, 3, 4, 0.9, 0]]) for _ in kwargs["source"].sources]


@pytest.mark.parametrize(
    "confidence, classes, minimum",
    [(0, [0, 1], 0), (0.4, [0, 1], 0.4), ({"horse": 0.7, "cow": 0.5}, [1, 0], 0.5)],
)
def test_detector_batches_active_sources_without_tracking(confidence, classes, minimum):
    model = Model()
    detector = YoloDetector(
        model,
        YoloConfig(model="model.onnx", confidence=confidence),
        ("one", "two"),
        InferenceOptions(),
    )
    latest = frame(3)
    observations = detector.detect(
        {"one": (frame(0), frame(2), latest), "two": (frame(1),)}
    )
    assert set(observations) == {"one", "two"}
    assert model.calls[0]["batch"] == 2
    assert model.calls[0]["classes"] == classes
    assert model.calls[0]["conf"] == minimum
    assert "persist" not in model.calls[0]
    assert len(model.calls) == 1
    assert model.calls[0]["source"][0] is latest.image
    assert [item.date for item in observations["one"]] == [
        frame(0).date,
        frame(2).date,
        latest.date,
    ]


def test_tracking_preserves_source_slots_when_camera_is_temporarily_absent():
    model = Model()
    detector = YoloDetector(
        model,
        YoloConfig(model="model.onnx", tracking=True),
        ("one", "two"),
        InferenceOptions(),
    )
    first_frame, second_frame = frame(0, 10), frame(1, 20)
    first = detector.detect({"one": (first_frame,)})
    second = detector.detect({"two": (second_frame,)})
    assert set(first) == {"one"}
    assert set(second) == {"two"}
    first_batch, second_batch = (call["source"] for call in model.calls)
    assert isinstance(first_batch, InMemoryStreamBatch)
    assert first_batch.sources == second_batch.sources == ["source-0", "source-1"]
    assert second_batch.images[0] is first_frame.image
    assert second_batch.images[1] is second_frame.image
    assert all(call["persist"] and call["batch"] == 2 for call in model.calls)


def test_unknown_model_class_fails_with_available_names():
    with pytest.raises(ValueError, match="Unknown YOLO classes: chicken"):
        resolve_classes({0: "cow"}, {"chicken": 0.8})


@pytest.mark.parametrize("result_count", [1, 3])
def test_sdk_result_count_mismatch_never_discards_sources(monkeypatch, result_count):
    model = Model()
    monkeypatch.setattr(model, "predict", lambda **kwargs: [result()] * result_count)
    detector = YoloDetector(
        model, YoloConfig(model="model.onnx"), ("one", "two"), InferenceOptions()
    )
    with pytest.raises(ValueError, match="zip"):
        detector.detect({"one": (frame(0),), "two": (frame(1),)})


@pytest.mark.parametrize(
    "model_path, options",
    [("model.pt", InferenceOptions(core_ml=True)), ("model.onnx", InferenceOptions())],
)
def test_detectors_run_independently_of_each_other(model_path, options):
    together = Barrier(2)

    class ConcurrentModel(Model):
        def predict(self, **kwargs):
            together.wait(timeout=5)
            return super().predict(**kwargs)

    detectors = [
        YoloDetector(
            ConcurrentModel(),
            YoloConfig(model=model_path),
            ("camera",),
            options,
        )
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda detector: detector.detect({"camera": (frame(),)}), detectors
            )
        )
    assert all(result["camera"][-1].date == frame().date for result in results)


def test_inference_timing_is_summarised_instead_of_logged_per_batch(
    monkeypatch, caplog
):
    detector = YoloDetector(
        Model(), YoloConfig(model="model.onnx"), ("one",), InferenceOptions()
    )
    with caplog.at_level(logging.INFO, logger=yolo.__name__):
        detector.detect({"one": (frame(0),)})
        assert caplog.messages == []
        monkeypatch.setattr(yolo, "SUMMARY_SECONDS", 0)
        detector.detect({"one": (frame(1),)})
    [summary] = caplog.messages
    assert summary.startswith("Inference: 2 frame(s) in 2 batch(es)")


@pytest.mark.parametrize("tracking", [False, True])
def test_real_onnx_yolo_batching_tracking_and_session_lifetime(
    tmp_path, monkeypatch, tracking, caplog
):
    caplog.set_level(logging.INFO, logger="aidetector.adapters.inference.yolo")
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
    current = frame()
    image_ref = ref(current.image)
    later = Frame(current.date + timedelta(seconds=1), current.image)
    settings = config.detectors[0].yolo
    models = (ModelRequirements(str(path), image_size=64, batch_size=2),)
    with inference_runtime(config.onnx, models, "default") as options:
        with open_detector(
            settings, config.onnx, ("0", "1"), "default", options, tmp_path
        ) as detector:
            first = detector.detect({"0": (current,), "1": (current,)})
            second = detector.detect({"1": (later,)})
            assert set(first) == {"0", "1"}
            assert set(second) == {"1"}
            assert first["0"][0].confidence == {"cow": pytest.approx(0.9)}
            assert second["1"][0].date == later.date
            assert second["1"][0].boxes[0].x1 == 10
            assert (second["1"][0].boxes[0].track_id is not None) is tracking
            assert len(sessions) == 1
            assert "ONNX model providers: ['CPUExecutionProvider']" in caplog.text
            assert "image tensor processing: cpu; I/O binding: False" in caplog.text
            del current, later, first, second
            gc.collect()
            assert image_ref() is not None
        assert detector.model.predictor is None
        gc.collect()
        assert image_ref() is None
    assert ort.InferenceSession is count_sessions


def test_failed_detector_startup_releases_the_loaded_predictor(tmp_path, monkeypatch):
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
