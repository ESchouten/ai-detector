from datetime import datetime, timedelta

import numpy as np
import pytest
from ultralytics.engine.results import Results

from aidetector.adapters.inference.onnx import (
    InferenceOptions,
)
from aidetector.adapters.inference.yolo import (
    InMemoryStreamBatch,
    YoloDetector,
    map_observations,
    resolve_classes,
)
from aidetector.configuration import YoloConfig
from aidetector.domain.models import Frame


def result(boxes=()):
    return Results(
        orig_img=np.zeros((64, 64, 3), dtype=np.uint8),
        path="frame.jpg",
        names={0: "cow", 1: "horse"},
        boxes=np.asarray(boxes, dtype=np.float32).reshape(-1, 6),
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


def test_no_boxes_still_produce_unscored_observations_for_trailing_footage():
    observations = map_observations(result(), (frame(0), frame(1)), {0: ("cow", 0.5)})
    assert len(observations) == 2
    assert all(not item.confidence and not item.boxes for item in observations)


class Model:
    names = {0: "cow", 1: "horse"}
    predictor = None

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
    observations = detector.detect({"one": (frame(0),), "two": (frame(1),)})
    assert set(observations) == {"one", "two"}
    assert model.calls[0]["batch"] == 2
    assert model.calls[0]["classes"] == classes
    assert model.calls[0]["conf"] == minimum
    assert "persist" not in model.calls[0]


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
    assert resolve_classes({0: "cow"}, 0) == {0: ("cow", 0)}


@pytest.mark.parametrize("result_count", [1, 3])
def test_sdk_result_count_mismatch_never_discards_sources(monkeypatch, result_count):
    model = Model()
    monkeypatch.setattr(model, "predict", lambda **kwargs: [result()] * result_count)
    detector = YoloDetector(
        model, YoloConfig(model="model.onnx"), ("one", "two"), InferenceOptions()
    )
    with pytest.raises(ValueError, match="zip"):
        detector.detect({"one": (frame(0),), "two": (frame(1),)})
