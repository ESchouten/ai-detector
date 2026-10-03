from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest

from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import SourceBatch
from aidetector.domain.models import (
    BoundingBox,
    CaptureStamp,
    Frame,
    IdentityMatch,
    Observation,
)
from aidetector.domain.policy import EventPolicy


class ScoringDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frames):
        self.calls += 1
        return {
            source: (
                Observation(
                    batch[-1].date,
                    batch[-1].image,
                    {"cow": 0.9},
                    capture=batch[-1].capture,
                ),
            )
            for source, batch in frames.items()
        }


def test_no_detector_emits_only_the_latest_frame_for_each_source():
    pipeline = DetectionPipeline()
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    first = Frame(datetime(2026, 1, 1), image)
    latest = Frame(
        first.date + timedelta(seconds=1), image.copy(), CaptureStamp("camera", 1, 1)
    )

    events = pipeline.process(SourceBatch({"one": (first, latest), "two": (first,)}))

    assert [event.source for event in events] == ["one", "two"]
    for event, frame in zip(events, (latest, first), strict=True):
        assert len(event.observations) == 1
        assert event.best.date == frame.date
        assert event.best.image is frame.image
        assert event.best.capture is frame.capture
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


def test_observation_callback_receives_the_analyzed_frame_before_event_completion():
    published = []
    pipeline = DetectionPipeline(
        ScoringDetector(),
        EventPolicy(min_frames=3),
        publish_observation=lambda source, result: published.append((source, result)),
    )
    frame = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))

    assert pipeline.process(SourceBatch({"camera": (frame,)})) == []

    [(source, result)] = published
    assert source == "camera"
    assert result.image is frame.image
    assert result.date == frame.date
    assert result.confidence == {"cow": 0.9}


def test_snapshot_pipeline_publishes_without_fabricating_detections():
    published = []
    pipeline = DetectionPipeline(
        publish_observation=lambda source, result: published.append(result)
    )
    frame = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))

    pipeline.process(SourceBatch({"camera": (frame,)}))

    [result] = published
    assert result.image is frame.image
    assert result.confidence == {}
    assert result.boxes == ()


def test_identity_uses_only_new_inference_and_preserves_source_and_context():
    box = BoundingBox(0, 0, 4, 4, "cow", 0.9, 7)

    class ContextDetector:
        def detect(self, frames):
            return {
                source: tuple(
                    Observation(
                        frame.date,
                        frame.image,
                        {"cow": 0.9} if index == len(batch) - 1 else {},
                        (box,),
                    )
                    for index, frame in enumerate(batch)
                )
                for source, batch in frames.items()
            }

    calls, published = [], []

    class Identifier:
        def identify(self, source, observation):
            calls.append((source, observation))
            return replace(
                observation,
                boxes=(replace(box, identity=IdentityMatch(source, "Bella", 0.95)),),
            )

    pipeline = DetectionPipeline(
        ContextDetector(),
        EventPolicy(min_frames=1),
        publish_observation=lambda source, result: published.append((source, result)),
        identifier=Identifier(),
    )
    first = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))
    latest = Frame(first.date + timedelta(seconds=1), first.image.copy())
    other = Frame(first.date + timedelta(seconds=2), first.image.copy())

    events = pipeline.process(
        SourceBatch(
            {"one": (first, latest), "two": (other,)},
            finished_sources=("one", "two"),
        )
    )
    assert [(source, observation.date) for source, observation in calls] == [
        ("one", latest.date),
        ("two", other.date),
    ]
    assert [event.source for event in events] == ["one", "two"]
    [context, recognized] = events[0].observations
    assert context.date == first.date
    assert context.image is first.image
    assert context.confidence == {}
    assert context.boxes[0].identity is None
    assert recognized.image is latest.image
    assert recognized.confidence == {"cow": 0.9}
    assert recognized.boxes[0].track_id == 7
    assert recognized.boxes[0].identity == IdentityMatch("one", "Bella", 0.95)
    assert events[1].best.boxes[0].identity == IdentityMatch("two", "Bella", 0.95)
    assert published[0][1] is recognized
    assert published[1][1] is events[1].best
    assert pipeline.process(SourceBatch({}, advance_to=other.date)) == []
    assert len(calls) == 2


@pytest.mark.parametrize("detect", [False, True])
def test_processing_status_uses_latest_analyzed_capture_epoch_and_legacy_sources(
    detect,
):
    reports = []
    pipeline = DetectionPipeline(
        ScoringDetector() if detect else None, report_status=reports.append
    )
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    first = Frame(datetime(2026, 1, 1), image, CaptureStamp("old", 4, 4))
    current = Frame(
        first.date + timedelta(seconds=1), image, CaptureStamp("current", 0, 5)
    )
    legacy = Frame(first.date, image)
    pipeline.process(SourceBatch({"camera": (first, current), "file": (legacy,)}))
    kind = "inference" if detect else "processed"
    assert [(event.kind, event.source, event.source_epoch) for event in reports] == [
        (kind, "camera", "current"),
        (kind, "file", None),
    ]
