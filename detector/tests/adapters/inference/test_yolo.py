import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event, get_ident
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from ultralytics.engine.results import Results

from aidetector.adapters.inference import MpsInferenceError, yolo
from aidetector.adapters.inference.onnx import InferenceOptions
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


MIB = 2**20


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(yolo, "perf_counter", lambda: now[0])
    return now


def reports(clock, watch, memory, count, *, per_call, calls=2000):
    """What a detector reports every half minute, and whether memory is leaking."""
    verdicts = []
    for _ in range(count):
        clock[0] += yolo.SUMMARY_SECONDS
        watch.calls += calls
        memory += per_call * calls
        verdicts.append(watch.growing(memory))
    return memory, verdicts


@pytest.mark.parametrize("calls, reports_until_fresh", [(2000, 2), (30, 69)])
def test_apple_gpu_memory_that_grows_with_every_call_asks_for_a_fresh_process(
    clock, calls, reports_until_fresh
):
    watch = yolo._MpsLeak()
    assert watch.growing(1236 * MIB) is False
    # An M6 with macOS 27 loses about 1 KiB per call, and 64 KiB from call 131072 on.
    memory, slow = reports(clock, watch, 1236 * MIB, 64, per_call=2**10, calls=calls)
    assert not any(slow)
    _, fast = reports(clock, watch, memory, 80, per_call=2**16, calls=calls)
    # A minute of it, and 128 MiB, tell a leak from a camera that joined.
    assert fast.index(True) + 1 == reports_until_fresh


def test_memory_that_grows_while_models_warm_up_or_only_once_is_not_a_leak(clock):
    watch = yolo._MpsLeak()
    assert watch.growing(0) is False
    # Cameras connect one after another, each with pictures of another size.
    memory, warming = reports(clock, watch, 0, 19, per_call=2**16)
    assert not any(warming)
    memory, settled = reports(clock, watch, memory, 10, per_call=0)
    # A camera that joins a day later adds its share once.
    memory, joined = reports(clock, watch, memory, 1, per_call=2**18)
    _, after = reports(clock, watch, memory, 10, per_call=0)
    assert not any(settled + joined + after)


def test_detectors_that_report_together_are_judged_once_per_period(clock):
    watch = yolo._MpsLeak()
    watch.growing(0)
    clock[0] = yolo.LEAK_WARM_UP_SECONDS
    memory = 0
    for _ in range(4):
        clock[0] += yolo.SUMMARY_SECONDS
        watch.calls += 2000
        memory += 2000 * 2**16
        first = watch.growing(memory)
        # The second detector reports a moment later, when nothing has grown yet.
        clock[0] += 0.1
        watch.calls += 5
        assert watch.growing(memory) is False
    assert first is True


@pytest.mark.parametrize("calls_per_report, leaking", [(1, True), (20000, False)])
def test_a_leaking_apple_gpu_stops_the_detector_for_a_fresh_process(
    monkeypatch, clock, caplog, calls_per_report, leaking
):
    memory = [1236 * MIB]

    def grow():
        memory[0] += 200 * MIB
        return memory[0]

    monkeypatch.setattr(torch.mps, "synchronize", lambda: None)
    monkeypatch.setattr(torch.mps, "current_allocated_memory", lambda: 121 * MIB)
    monkeypatch.setattr(torch.mps, "driver_allocated_memory", grow)
    monkeypatch.setattr(yolo, "_MPS_LEAK", yolo._MpsLeak())
    monkeypatch.setattr(yolo, "LEAK_WARM_UP_SECONDS", 0)
    detector = YoloDetector(
        Model(),
        YoloConfig(model="model.pt"),
        ("one",),
        InferenceOptions(native_mps=True),
    )

    def report():
        # Between reports the detector analyses pictures without summarising them.
        for _ in range(calls_per_report - 1):
            detector.detect({"one": (frame(),)})
        clock[0] += yolo.SUMMARY_SECONDS
        detector.detect({"one": (frame(),)})

    with caplog.at_level(logging.INFO, logger=yolo.__name__):
        report()
        report()
        if leaking:
            with pytest.raises(MpsInferenceError, match="keeps growing"):
                report()
        else:
            # 200 MiB over twenty thousand pictures is what a healthy Mac may add.
            report()
    assert caplog.messages[-1] == (
        "Apple GPU memory: 121 MiB held by PyTorch, 1836 MiB by the whole process"
    )
