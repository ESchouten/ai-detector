from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event, get_ident
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from ultralytics.engine.results import Results

from aidetector.adapters.inference import MpsInferenceError
from aidetector.adapters.inference.device import mps_inference
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


@pytest.mark.parametrize(
    "device",
    [
        "cpu",
        pytest.param(
            "mps",
            marks=pytest.mark.skipif(
                not torch.backends.mps.is_available(), reason="Requires Apple MPS"
            ),
        ),
    ],
)
def test_real_ultralytics_results_are_mapped_at_the_boundary(device):
    observations = map_observations(
        result(
            [
                [10, 20, 30, 40, 0.8, 0],
                [35, 20, 50, 40, 0.6, 0],
                [1, 2, 3, 4, 0.6, 1],
            ]
        ).to(device),
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


@pytest.mark.parametrize("tracking", [False, True])
@pytest.mark.parametrize("specified", [False, True])
def test_optional_nms_and_tracker_settings_preserve_sdk_defaults(tracking, specified):
    model = Model()
    settings = {"iou": 0.45, "tracker": "bytetrack.yaml"} if specified else {}
    detector = YoloDetector(
        model,
        YoloConfig(model="model.onnx", tracking=tracking, **settings),
        ("one",),
        InferenceOptions(),
    )
    detector.detect({"one": (frame(),)})
    arguments = model.calls[0]
    assert ("iou" in arguments) is specified
    if specified:
        assert arguments["iou"] == 0.45
    assert ("tracker" in arguments) is (specified and tracking)
    if specified and tracking:
        assert arguments["tracker"] == "bytetrack.yaml"


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


@pytest.mark.parametrize("tracking", [False, True])
@pytest.mark.parametrize("stage", ["predict", "transfer", "synchronize"])
def test_mps_accelerator_failure_requests_a_fresh_process(monkeypatch, tracking, stage):
    error = torch.AcceleratorError("index -123 is out of bounds for dimension 1")

    def fail_at(current):
        if current == stage:
            raise error

    class FailingModel:
        names = {0: "cow"}

        def predict(self, **kwargs):
            fail_at("predict")

            def transfer():
                fail_at("transfer")
                return ()

            yield SimpleNamespace(boxes=SimpleNamespace(cpu=transfer), speed={})

        track = predict

    monkeypatch.setattr(torch.mps, "synchronize", lambda: fail_at("synchronize"))
    detector = YoloDetector(
        FailingModel(),
        YoloConfig(model="model.pt", tracking=tracking),
        ("camera",),
        InferenceOptions(native_mps=True),
    )
    with pytest.raises(MpsInferenceError, match="fresh detector process") as raised:
        detector.detect({"camera": (frame(),)})
    assert raised.value.__cause__ is error


@pytest.mark.parametrize("native_mps", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, torch.AcceleratorError])
def test_only_mps_accelerator_errors_request_recovery(
    monkeypatch, native_mps, error_type
):
    error = error_type("inference failed")
    model = Model()

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(model, "predict", fail)
    detector = YoloDetector(
        model,
        YoloConfig(model="model.pt"),
        ("camera",),
        InferenceOptions(native_mps=native_mps),
    )
    if native_mps and error_type is torch.AcceleratorError:
        with pytest.raises(MpsInferenceError):
            detector.detect({"camera": (frame(),)})
    else:
        with pytest.raises(error_type) as raised:
            detector.detect({"camera": (frame(),)})
        assert raised.value is error


def test_yolo_waits_for_other_models_using_the_shared_mps_scope(monkeypatch):
    entered, release, yolo_started, yolo_entered = (Event() for _ in range(4))
    calls = []
    monkeypatch.setattr(torch.mps, "synchronize", lambda: calls.append("synchronize"))

    def identify():
        with mps_inference():
            entered.set()
            assert release.wait(5)
            calls.append("identity transfer")

    class GpuModel(Model):
        def predict(self, **kwargs):
            yolo_entered.set()
            calls.append("yolo")
            return super().predict(**kwargs)

    detector = YoloDetector(
        GpuModel(),
        YoloConfig(model="model.pt"),
        ("camera",),
        InferenceOptions(native_mps=True),
    )

    def detect():
        yolo_started.set()
        return detector.detect({"camera": (frame(),)})

    with ThreadPoolExecutor(max_workers=2) as pool:
        identity = pool.submit(identify)
        try:
            assert entered.wait(5)
            detection = pool.submit(detect)
            assert yolo_started.wait(5)
            assert not yolo_entered.wait(0.1), (
                "Identity and YOLO GPU dispatch overlapped"
            )
        finally:
            release.set()
        identity.result(timeout=5)
        assert detection.result(timeout=5)["camera"][-1].date == frame().date

    assert calls == ["identity transfer", "synchronize", "yolo", "synchronize"]


@pytest.mark.parametrize("tracking", [False, True])
@pytest.mark.parametrize("blocked_stage", ["predict", "transfer", "synchronize"])
def test_mps_detectors_share_exclusive_gpu_access_through_result_transfer(
    monkeypatch, tracking, blocked_stage
):
    blocked, release, second_started, second_entered = (Event() for _ in range(4))
    calls, owners = [], {}

    def observe(stage, name):
        calls.append((stage, name))
        if stage == "predict" and name == "second":
            second_entered.set()
        if name == "first" and stage == blocked_stage:
            blocked.set()
            assert release.wait(5), "Test did not release the first GPU operation"

    class GpuModel:
        names = {0: "cow"}

        def __init__(self, name):
            self.name = name

        def predict(self, **kwargs):
            owners[get_ident()] = self.name
            observe("predict", self.name)

            def transfer():
                observe("transfer", self.name)
                return ()

            # Deferred SDK iteration and CPU transfers both belong inside the lock.
            yield SimpleNamespace(boxes=SimpleNamespace(cpu=transfer), speed={})

        track = predict

    monkeypatch.setattr(
        torch.mps, "synchronize", lambda: observe("synchronize", owners[get_ident()])
    )
    detectors = [
        YoloDetector(
            GpuModel(name),
            YoloConfig(model="model.pt", tracking=tracking),
            ("camera",),
            InferenceOptions(native_mps=True),
        )
        for name in ("first", "second")
    ]
    batch = {"camera": (frame(),)}

    def second():
        second_started.set()
        return detectors[1].detect(batch)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(detectors[0].detect, batch)
        try:
            assert blocked.wait(5)
            second_result = pool.submit(second)
            assert second_started.wait(5)
            assert not second_entered.wait(0.1), "MPS operations overlapped"
        finally:
            release.set()
        assert first_result.result(timeout=5)["camera"][-1].date == frame().date
        assert second_result.result(timeout=5)["camera"][-1].date == frame().date
    assert calls == [
        (stage, name)
        for name in ("first", "second")
        for stage in ("predict", "transfer", "synchronize")
    ]


@pytest.mark.parametrize(
    "model_path, native_mps", [("model.pt", False), ("model.onnx", True)]
)
def test_other_backends_retain_independent_detector_execution(model_path, native_mps):
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
            InferenceOptions(native_mps=native_mps),
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
