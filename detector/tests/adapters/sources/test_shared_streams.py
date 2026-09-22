import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from queue import Queue
from threading import Event

import numpy as np
import pytest

from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.sources.streams import StreamPool, StreamSource
from aidetector.bootstrap import run_application
from aidetector.configuration import Config
from aidetector.domain.models import Frame
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
        assert reports[0].kind == "frame"
        assert reports[0].source == "0"
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
        frame = Frame(
            started + timedelta(seconds=instant), np.zeros((64, 64, 3), dtype=np.uint8)
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
    frame = Frame(datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8))
    source.publish("0", frame, 0)
    source.publish("0", frame, 1)
    source.publish("1", frame, 1)
    batch = next(source.batches())
    assert set(batch.frames) == {"0", "1"}
    assert len(batch.frames["0"]) == len(batch.frames["1"]) == 1


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


def test_reconnection_is_shared_by_subscribers(cameras):
    streams = StreamPool()
    first, second = streams.subscribe(("0",)), streams.subscribe(("0",))
    left, right = first.batches(), second.batches()
    camera = cameras["0"]
    with running(streams, cameras):
        camera.send(1)
        camera.flush()
        assert pixels(next(left), "0") == pixels(next(right), "0") == [1]
        camera.finish()
        camera.send(2)
        camera.flush()
        assert pixels(next(left), "0") == pixels(next(right), "0") == [2]
        assert camera.opens == 2
    assert camera.releases == 2


@pytest.mark.parametrize("use_yolo", [False, True])
def test_application_shares_capture_across_detectors_and_archives_for_both(
    tmp_path, monkeypatch, cameras, use_yolo
):
    stop = Event()
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
        task = workers.submit(run_application, config, tmp_path, tmp_path, stop)
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
    assert cameras["0"].opens == cameras["0"].releases == 1
    for label in delivered:
        [metadata] = (tmp_path / "detections" / label).glob(
            "unvalidated/*/metadata.json"
        )
        assert json.loads(metadata.read_text())["detections"] == 1
        assert metadata.with_name("best.jpg").stat().st_size > 0
