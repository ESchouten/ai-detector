from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event, current_thread
from weakref import ref

import numpy as np
import pytest

from aidetector.adapters.sources.streams import StreamPool
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import (
    DeliveryError,
    SourceBatch,
    SourceError,
    ValidationUnavailable,
)
from aidetector.domain.models import Frame
from aidetector.domain.policy import Cooldown, ExportPolicy
from aidetector.runtime import DetectorWorker, run_detectors


class FiniteSource:
    def __init__(self, count=5):
        self.count = count
        self.closed = False
        self.read = 0
        self.third_frame = Event()
        self.fourth_frame = Event()

    def batches(self):
        try:
            for index in range(self.count):
                if self.closed:
                    return
                self.read += 1
                if self.read == 3:
                    self.third_frame.set()
                if self.read == 4:
                    self.fourth_frame.set()
                yield SourceBatch(
                    {
                        "camera": (
                            Frame(
                                datetime(2026, 1, 1) + timedelta(seconds=index),
                                np.zeros((8, 8, 3), dtype=np.uint8),
                            ),
                        )
                    }
                )
        finally:
            self.closed = True

    def close(self):
        self.closed = True


class Exporter:
    def __init__(self, error=None, wait=None):
        self.events = []
        self.error = error
        self.wait = wait
        self.entered = Event()

    def export(self, result):
        self.entered.set()
        if self.wait is not None:
            assert self.wait.wait(5)
        if self.error is not None:
            raise self.error
        self.events.append(result.event)


def worker(source, exporter, pending=1, name="detector"):
    return DetectorWorker(
        source,
        DetectionPipeline(),
        EventDelivery((Destination("test", exporter, ExportPolicy()),), Cooldown()),
        pending_events=pending,
        name=name,
    )


def test_worker_drains_all_events_and_closes_source():
    source, exporter = FiniteSource(), Exporter()
    original_name = current_thread().name
    stats = worker(source, exporter).run()
    assert current_thread().name == original_name
    assert source.closed
    assert stats.events == 5
    assert not stats.failed
    assert [event.start.second for event in exporter.events] == list(range(5))


def test_supervisor_stops_and_joins_health_monitor_after_finite_inputs_end():
    class Health:
        def __init__(self):
            self.stopped = Event()
            self.finished = Event()

        def run(self):
            assert self.stopped.wait(5), "Health monitor kept running after EOF"
            self.finished.set()

        def stop(self):
            self.stopped.set()

    health = Health()
    detector = worker(FiniteSource(), Exporter())
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run_detectors, (detector,), health)
        try:
            [stats] = task.result(timeout=2)
        finally:
            health.stop()
            detector.stop()
    assert stats.events == 5
    assert health.finished.is_set()


def test_delivery_queue_applies_backpressure_and_stop_drains_accepted_work():
    release = Event()
    source, exporter = FiniteSource(100), Exporter(wait=release)
    detector = worker(source, exporter, pending=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(detector.run)
        try:
            assert exporter.entered.wait(2)
            assert source.third_frame.wait(2)
            assert not source.fourth_frame.wait(0.05)
            detector.stop()
        finally:
            release.set()
        stats = task.result(timeout=5)
    assert stats.events == 3
    assert len(exporter.events) == 3


def test_expected_delivery_failures_are_counted_and_other_events_continue():
    source = FiniteSource(3)
    stats = worker(source, Exporter(error=DeliveryError("HTTP status 503"))).run()
    assert stats.events == 3
    assert stats.delivery_failures == 3
    assert stats.failed


def test_validation_failures_are_counted_without_stopping_later_events():
    class UnavailableValidator:
        def validate(self, event):
            raise ValidationUnavailable("Verifier is offline")

    detector = DetectorWorker(
        FiniteSource(3),
        DetectionPipeline(),
        EventDelivery((), Cooldown(), UnavailableValidator()),
    )
    stats = detector.run()
    assert stats.events == stats.validation_failures == 3
    assert stats.delivery_failures == 0
    assert stats.failed


def test_unexpected_delivery_failure_stops_producer_without_deadlock():
    source = FiniteSource(100)
    detector = worker(source, Exporter(error=TypeError("broken exporter")))
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(detector.run)
        with pytest.raises(TypeError, match="broken exporter"):
            task.result(timeout=5)
    assert source.closed


def test_supervisor_stops_other_detectors_when_one_fails():
    class WaitingSource:
        def __init__(self):
            self.stopped = Event()

        def batches(self):
            assert self.stopped.wait(5)
            yield SourceBatch({})

        def close(self):
            self.stopped.set()

    waiting = WaitingSource()
    good = worker(waiting, Exporter())
    bad = worker(FiniteSource(1), Exporter(error=TypeError("failure")))
    with pytest.raises(TypeError, match="failure"):
        run_detectors((good, bad))
    assert waiting.stopped.is_set()


def test_concurrent_detector_failures_are_all_reported(caplog):
    started = Barrier(2)

    class BrokenSource(FiniteSource):
        def __init__(self, message):
            super().__init__(count=0)
            self.message = message

        def batches(self):
            started.wait(timeout=5)
            yield from super().batches()
            raise SourceError(self.message)

    first = BrokenSource("First source failed")
    second = BrokenSource("Second source failed")
    with pytest.raises(SourceError, match="source failed"):
        run_detectors(
            (
                worker(first, Exporter(), name="detector-1"),
                worker(second, Exporter(), name="detector-2"),
            )
        )
    assert first.closed and second.closed
    assert "First source failed" in caplog.text
    assert "Second source failed" in caplog.text
    assert {
        record.threadName
        for record in caplog.records
        if record.message == "Detector worker failed"
    } == {"detector-1-processing", "detector-2-processing"}


def test_stream_stop_wakes_waiter_even_without_frames(monkeypatch):
    attempted = Event()

    class UnavailableCapture:
        def __init__(self, *args):
            attempted.set()

        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.cv2.VideoCapture", UnavailableCapture
    )
    streams = StreamPool()
    source = streams.subscribe(("rtsp://camera",))
    with streams.open(), ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(lambda: list(source.batches()))
        assert attempted.wait(2)
        source.close()
        assert task.result(timeout=2) == []


def test_source_failure_reaches_caller_and_closes_input():
    class BrokenSource(FiniteSource):
        def batches(self):
            yield from super().batches()
            raise SourceError("decoding failed")

    source = BrokenSource(1)
    exporter = Exporter()
    original_name = current_thread().name
    with pytest.raises(SourceError, match="decoding failed"):
        worker(source, exporter).run()
    assert current_thread().name == original_name
    assert len(exporter.events) == 1
    assert source.closed


def test_completed_event_is_released_while_waiting_for_more_input():
    released = Event()
    stopped = Event()

    class HoldingSource:
        def batches(self):
            yield SourceBatch(
                {
                    "camera": (
                        Frame(
                            datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8)
                        ),
                    )
                }
            )
            assert stopped.wait(5)

        def close(self):
            stopped.set()

    class ObservingExporter:
        def export(self, result):
            self.event = ref(result.event, lambda _: released.set())

    detector = worker(HoldingSource(), ObservingExporter())
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(detector.run)
        try:
            assert released.wait(2), "An idle worker retained the completed event"
        finally:
            detector.stop()
        assert task.result(timeout=5).events == 1
