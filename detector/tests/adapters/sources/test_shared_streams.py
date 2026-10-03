import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from queue import Queue
from threading import Event

import numpy as np
import pytest

from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.media.images import shrink_image
from aidetector.adapters.operational_status import source_key
from aidetector.adapters.sources.streams import CapturedFrame, StreamPool, StreamSource
from aidetector.bootstrap import run_application
from aidetector.configuration import Config
from aidetector.domain.models import CaptureStamp, Frame
from tests.support.onnx_model import write_detection_model


class Camera:
    """Drive a capture with explicit frames and barriers, without timing sleeps."""

    def __init__(self):
        self.inputs = Queue()
        self.opened = Event()
        self.opens = 0
        self.releases = 0

    def isOpened(self):
        return True

    def read(self):
        item = self.inputs.get(timeout=5)
        while isinstance(item, Event):
            item.set()
            item = self.inputs.get(timeout=5)
        if isinstance(item, Exception):
            raise item
        return (False, None) if item is None else (True, item)

    def release(self):
        self.releases += 1

    def send(self, value):
        self.inputs.put(np.full((64, 64, 3), value, dtype=np.uint8))

    def flush(self):
        reached = Event()
        self.inputs.put(reached)
        assert reached.wait(3), "Capture did not publish the preceding frames"

    def finish(self):
        self.inputs.put(None)


@pytest.fixture
def cameras(monkeypatch):
    devices = {str(index): Camera() for index in range(3)}

    def open_camera(source, *args):
        camera = devices[str(source)]
        camera.opens += 1
        camera.opened.set()
        return camera

    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.cv2.VideoCapture", open_camera
    )
    return devices


@contextmanager
def running(streams, cameras):
    with streams.open():
        try:
            yield
        finally:
            for camera in cameras.values():
                camera.finish()


def pixels(batch, source):
    return [int(frame.image[0, 0, 0]) for frame in batch.frames[source]]


def test_capture_status_tracks_decoded_frames_and_disconnects(cameras):
    reports = []
    offline = Event()

    def report(event):
        reports.append(event)
        if event.kind == "offline":
            offline.set()

    streams = StreamPool(report)
    streams.subscribe(("0",))
    with running(streams, cameras):
        camera = cameras["0"]
        camera.send(1)
        camera.flush()
        assert [event.kind for event in reports] == ["source_epoch", "frame"]
        assert all(event.source == "0" for event in reports)
        assert reports[0].source_epoch
        camera.finish()
        assert offline.wait(3), "A failed capture read did not report disconnection"
        assert reports[-1].kind == "offline"


def test_one_camera_feeds_fast_and_slow_detectors_without_consuming_each_others_frames(
    cameras,
):
    streams = StreamPool()
    fast = streams.subscribe(("0",), retention=2)
    slow = streams.subscribe(("0",), retention=3)
    fast_batches, slow_batches = fast.batches(), slow.batches()
    camera = cameras["0"]
    with running(streams, cameras):
        for value in range(1, 6):
            camera.send(value)
            camera.flush()
            assert pixels(next(fast_batches), "0") == [value]
        assert pixels(next(slow_batches), "0") == [3, 4, 5]
        fast.close()
        camera.send(6)
        camera.flush()
        assert pixels(next(slow_batches), "0") == [6]
        assert list(fast_batches) == []
        assert camera.opens == 1
        assert camera.releases == 0
    assert camera.releases == 1
    assert list(slow_batches) == []


def test_overlapping_source_groups_open_each_camera_once_and_share_read_only_pixels(
    cameras,
):
    streams = StreamPool()
    first = streams.subscribe(("0", "1"))
    second = streams.subscribe(("1", "2"))
    with running(streams, cameras):
        for source, camera in cameras.items():
            camera.send(int(source))
            camera.flush()
        left, right = next(first.batches()), next(second.batches())
        assert set(left.frames) == {"0", "1"}
        assert set(right.frames) == {"1", "2"}
        assert left.frames["1"][0].image is right.frames["1"][0].image
        assert left.frames["1"][0].date == right.frames["1"][0].date
        with pytest.raises(ValueError, match="read-only"):
            left.frames["1"][0].image[0, 0, 0] = 99
        assert pixels(right, "1") == [1]
        assert [camera.opens for camera in cameras.values()] == [1, 1, 1]
    assert [camera.releases for camera in cameras.values()] == [1, 1, 1]


def test_each_subscription_keeps_its_own_sampling_resolution_and_retention():
    fast = StreamSource(("0",), width=32, retention=3, interval=0)
    slow = StreamSource(("0",), width=16, retention=2, interval=1)
    started = datetime(2026, 1, 1)
    for instant in (0, 0.5, 1, 1.5, 2):
        frame = CapturedFrame(
            Frame(
                started + timedelta(seconds=instant),
                np.zeros((64, 64, 3), dtype=np.uint8),
            )
        )
        fast.publish("0", frame, instant)
        slow.publish("0", frame, instant)
    fast_frames = next(fast.batches()).frames["0"]
    slow_frames = next(slow.batches()).frames["0"]
    assert [(frame.date - started).total_seconds() for frame in fast_frames] == [
        1,
        1.5,
        2,
    ]
    assert [(frame.date - started).total_seconds() for frame in slow_frames] == [1, 2]
    assert all(frame.image.shape == (32, 32, 3) for frame in fast_frames)
    assert all(frame.image.shape == (16, 16, 3) for frame in slow_frames)
    assert all(
        not frame.image.flags.writeable for frame in (*fast_frames, *slow_frames)
    )


def test_sampling_one_camera_does_not_suppress_another_camera():
    source = StreamSource(("0", "1"), interval=2)
    frame = CapturedFrame(
        Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))
    )
    source.publish("0", frame, 0)
    source.publish("0", frame, 1)
    source.publish("1", frame, 1)
    batch = next(source.batches())
    assert set(batch.frames) == {"0", "1"}
    assert len(batch.frames["0"]) == len(batch.frames["1"]) == 1


def test_resized_frames_are_shared_by_width_without_changing_pixels(cameras):
    streams = StreamPool()
    subscribers = [streams.subscribe(("0",), width=width) for width in (32, 33, 16)]
    batches = [source.batches() for source in subscribers]
    image = np.random.default_rng(42).integers(0, 256, (64, 96, 3), dtype=np.uint8)
    with running(streams, cameras):
        cameras["0"].inputs.put(image)
        cameras["0"].flush()
        frames = [next(batch).frames["0"][0] for batch in batches]
        assert frames[0] is frames[1]
        assert all(frame.capture is frames[0].capture for frame in frames)
        assert frames[0].capture.sequence == 0
        for frame, width in zip(frames, (32, 33, 16), strict=True):
            np.testing.assert_array_equal(frame.image, shrink_image(image, width))
            assert not frame.image.flags.writeable
        cameras["0"].inputs.put(np.full_like(image, 123))
        cameras["0"].flush()
        updated = next(batches[0]).frames["0"][0]
        assert updated is not frames[0]
        assert updated.capture.epoch == frames[0].capture.epoch
        assert updated.capture.sequence == 1
        assert updated.capture.monotonic_at > frames[0].capture.monotonic_at
        assert np.all(updated.image == 123)
        np.testing.assert_array_equal(frames[0].image, shrink_image(image, 32))


def test_skipped_samples_do_not_resize_and_same_width_resizes_only_once(monkeypatch):
    import cv2

    resize = cv2.resize
    sizes = []

    def record_resize(image, size, **kwargs):
        sizes.append(size)
        return resize(image, size, **kwargs)

    monkeypatch.setattr(cv2, "resize", record_resize)
    subscribers = [StreamSource(("0",), width=32, interval=1) for _ in range(2)]
    for instant in (0, 0.5, 1):
        frame = CapturedFrame(
            Frame(datetime.now(), np.zeros((64, 64, 3), dtype=np.uint8))
        )
        for source in subscribers:
            source.publish("0", frame, instant)
    assert sizes == [(32, 32), (32, 32)]
    for source in subscribers:
        source.close()
        source.publish(
            "0",
            CapturedFrame(Frame(datetime.now(), np.zeros((64, 64, 3), dtype=np.uint8))),
            2,
        )
    assert len(sizes) == 2


def test_shared_capture_failure_reaches_every_subscriber(cameras):
    streams = StreamPool()
    first, second = streams.subscribe(("0",)), streams.subscribe(("0",))
    with running(streams, cameras), ThreadPoolExecutor(max_workers=2) as workers:
        tasks = [workers.submit(next, source.batches()) for source in (first, second)]
        cameras["0"].inputs.put(TypeError("Decoder failed unexpectedly"))
        for task in tasks:
            with pytest.raises(TypeError, match="Decoder failed unexpectedly"):
                task.result(timeout=3)
    assert cameras["0"].opens == cameras["0"].releases == 1


def test_reconnection_is_shared_by_subscribers(cameras, caplog):
    caplog.set_level("INFO")
    streams = StreamPool()
    first, second = streams.subscribe(("0",)), streams.subscribe(("0",))
    left, right = first.batches(), second.batches()
    camera = cameras["0"]
    with running(streams, cameras):
        camera.send(1)
        camera.flush()
        before = next(left).frames["0"][0]
        assert int(before.image[0, 0, 0]) == pixels(next(right), "0")[0] == 1
        camera.finish()
        camera.send(2)
        camera.flush()
        after = next(left).frames["0"][0]
        shared = next(right).frames["0"][0]
        assert int(after.image[0, 0, 0]) == int(shared.image[0, 0, 0]) == 2
        assert after.capture is shared.capture
        assert before.capture.epoch != after.capture.epoch
        assert before.capture.sequence == after.capture.sequence == 0
        assert camera.opens == 2
    assert camera.releases == 2
    openings = [
        message
        for message in caplog.messages
        if "opening 0 for 2 detector(s)" in message
    ]
    assert len(openings) == 2
    assert "attempt=1" in openings[0]
    assert "attempt=2" in openings[1]
    assert all(source_key("0")[:12] in message for message in openings)
    assert (
        sum(
            "receiving 64x64 frames; dtype=uint8" in message
            for message in caplog.messages
        )
        == 2
    )


def test_new_epoch_drops_only_its_cameras_unread_frames_and_sampling_wait():
    subscription = StreamSource(("one", "two"), retention=3, interval=10, width=16)
    started = datetime(2026, 1, 1)

    def publish(source, value, at, epoch):
        frame = Frame(
            started + timedelta(seconds=at),
            np.full((32, 32, 3), value, dtype=np.uint8),
            CaptureStamp(epoch, 0, at),
        )
        subscription.publish(source, CapturedFrame(frame), at)
        return frame

    publish("one", 1, 0, "before")
    other = publish("two", 2, 0.1, "other")
    replacement = publish("one", 3, 0.2, "after")
    batch = next(subscription.batches())

    assert pixels(batch, "one") == [3]
    assert pixels(batch, "two") == [2]
    assert batch.frames["one"][0].capture is replacement.capture
    assert batch.frames["two"][0].capture is other.capture
    assert batch.frames["one"][0].image.shape == (16, 16, 3)


def test_geometry_change_starts_a_new_epoch_only_for_the_changed_camera(cameras):
    statuses = []
    streams = StreamPool(statuses.append)
    subscription = streams.subscribe(("0", "1"), width=32)
    batches = subscription.batches()
    with running(streams, cameras):
        for source in ("0", "1"):
            cameras[source].send(1)
            cameras[source].flush()
        first = next(batches)
        cameras["0"].inputs.put(np.zeros((128, 128, 3), dtype=np.uint8))
        cameras["0"].flush()
        cameras["1"].send(2)
        cameras["1"].flush()
        following = next(batches)

    before = first.frames["0"][0]
    changed = following.frames["0"][0]
    assert before.image.shape == changed.image.shape == (32, 32, 3)
    assert before.capture.epoch != changed.capture.epoch
    assert changed.capture.sequence == 0
    assert first.frames["1"][0].capture.epoch == following.frames["1"][0].capture.epoch
    assert following.frames["1"][0].capture.sequence == 1
    zero = [event for event in statuses if event.source == "0"]
    assert [event.kind for event in zero[:4]] == [
        "source_epoch",
        "frame",
        "source_epoch",
        "frame",
    ]
    assert [event.source_epoch for event in zero if event.kind == "source_epoch"] == [
        before.capture.epoch,
        changed.capture.epoch,
    ]
    assert (
        sum(event.kind == "source_epoch" and event.source == "1" for event in statuses)
        == 1
    )


@pytest.mark.parametrize(
    ("elapsed", "wall_elapsed", "interrupted"),
    [
        (1, 1, False),
        (5, 5, False),
        (6, 1, True),
        (1, 6, True),
        (-1, 1, True),
        (1, -1, True),
    ],
)
def test_capture_timing_break_resets_even_without_reopening(
    cameras, monkeypatch, elapsed, wall_elapsed, interrupted
):
    clock = [100.0, datetime(2026, 1, 1)]

    class WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[1]

    monkeypatch.setattr("aidetector.adapters.sources.streams.datetime", WallClock)
    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.monotonic", lambda: clock[0]
    )
    statuses = []
    streams = StreamPool(statuses.append)
    fast = streams.subscribe(("0",))
    slow = streams.subscribe(("0",), interval=60)
    batches = fast.batches()
    camera = cameras["0"]
    with running(streams, cameras):
        camera.send(1)
        camera.flush()
        before = next(batches).frames["0"][0]
        clock[:] = [100.0 + elapsed, clock[1] + timedelta(seconds=wall_elapsed)]
        camera.send(2)
        camera.flush()
        after = next(batches).frames["0"][0]
        slow_batch = next(slow.batches())

    assert camera.opens == 1
    assert (before.capture.epoch != after.capture.epoch) is interrupted
    assert after.capture.sequence == (0 if interrupted else 1)
    assert pixels(slow_batch, "0") == ([2] if interrupted else [1])
    epochs = [event.source_epoch for event in statuses if event.kind == "source_epoch"]
    assert epochs == (
        [before.capture.epoch, after.capture.epoch]
        if interrupted
        else [before.capture.epoch]
    )


@pytest.mark.parametrize("use_yolo", [False, True])
def test_application_shares_capture_across_detectors_and_archives_for_both(
    tmp_path, monkeypatch, cameras, use_yolo
):
    stop = Event()
    reports = []
    delivered = {label: Event() for label in ("first", "second")}
    original_export = DiskExporter.export

    def record_export(exporter, result):
        original_export(exporter, result)
        delivered[exporter.config.directory].set()

    monkeypatch.setattr(DiskExporter, "export", record_export)
    model = tmp_path / "model.onnx"
    if use_yolo:
        write_detection_model(model)
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "0"},
                    "yolo": {
                        "model": str(model),
                        "imgsz": 64,
                        "frames_min": 1,
                        "timeout": 0.01,
                        "tracking": True,
                    }
                    if use_yolo
                    else None,
                    "exporters": {"disk": {"directory": label}},
                }
                for label in delivered
            ],
            "onnx": {"provider": "CPUExecutionProvider"},
        }
    )
    with ThreadPoolExecutor(max_workers=1) as workers:
        task = workers.submit(
            run_application,
            config,
            tmp_path,
            tmp_path,
            stop,
            report_status=reports.append,
        )
        try:
            # Both real models and first-use SDK imports finish before capture starts.
            assert cameras["0"].opened.wait(30)
            cameras["0"].send(50)
            assert all(event.wait(3) for event in delivered.values())
        finally:
            stop.set()
            cameras["0"].finish()
        stats = task.result(timeout=5)
    assert [item.events for item in stats] == [1, 1]
    [epoch] = [event.source_epoch for event in reports if event.kind == "source_epoch"]
    completed_kind = "inference" if use_yolo else "processed"
    assert sorted(
        (event.rule_id, event.source_epoch)
        for event in reports
        if event.kind == completed_kind
    ) == [("detector-1", epoch), ("detector-2", epoch)]
    assert cameras["0"].opens == cameras["0"].releases == 1
    for label in delivered:
        [metadata] = (tmp_path / "detections" / label).glob(
            "unvalidated/*/metadata.json"
        )
        assert json.loads(metadata.read_text())["detections"] == 1
        assert metadata.with_name("best.jpg").stat().st_size > 0
