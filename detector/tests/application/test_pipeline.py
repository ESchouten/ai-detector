from datetime import datetime, timedelta

import numpy as np

from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import SourceBatch
from aidetector.domain.models import Frame, Observation
from aidetector.domain.policy import EventPolicy


class ScoringDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frames):
        self.calls += 1
        return {
            source: (Observation(batch[-1].date, batch[-1].image, {"cow": 0.9}),)
            for source, batch in frames.items()
        }


def test_no_detector_emits_only_the_latest_frame_for_each_source():
    pipeline = DetectionPipeline()
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    first = Frame(datetime(2026, 1, 1), image)
    latest = Frame(first.date + timedelta(seconds=1), image.copy())

    events = pipeline.process(SourceBatch({"one": (first, latest), "two": (first,)}))

    assert [event.source for event in events] == ["one", "two"]
    for event, frame in zip(events, (latest, first), strict=True):
        assert len(event.observations) == 1
        assert event.best.date == frame.date
        assert event.best.image is frame.image
        assert event.best.confidence == {}
        assert event.best.boxes == ()
    assert pipeline.finish() == []


def test_no_detector_has_nothing_to_emit_on_idle_or_source_completion():
    pipeline = DetectionPipeline()

    assert pipeline.process(SourceBatch({}, advance_to=datetime(2026, 1, 1))) == []
    assert pipeline.process(SourceBatch({}, finished_sources=("camera",))) == []
    assert pipeline.finish() == []


def test_idle_live_batch_closes_an_event_without_running_empty_inference():
    detector = ScoringDetector()
    pipeline = DetectionPipeline(detector, EventPolicy(min_frames=1))
    frame = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))
    assert pipeline.process(SourceBatch({"camera": (frame,)})) == []
    assert pipeline.process(SourceBatch({}, frame.date + timedelta(seconds=4))) == []

    [event] = pipeline.process(SourceBatch({}, frame.date + timedelta(seconds=5)))

    assert event.source == "camera"
    assert event.best.image is frame.image
    assert detector.calls == 1
    assert pipeline.finish() == []


def test_source_completion_flushes_only_that_source_and_shutdown_flushes_the_rest():
    detector = ScoringDetector()
    pipeline = DetectionPipeline(detector, EventPolicy(min_frames=1))
    frame = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))
    assert pipeline.process(SourceBatch({"one": (frame,), "two": (frame,)})) == []

    [finished] = pipeline.process(SourceBatch({}, finished_sources=("one",)))
    [drained] = pipeline.finish()

    assert finished.source == "one"
    assert drained.source == "two"
    assert detector.calls == 1
    assert pipeline.finish() == []
