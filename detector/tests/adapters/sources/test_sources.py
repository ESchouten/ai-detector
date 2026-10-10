import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread

import cv2
import numpy as np
import pytest

from aidetector.adapters.sources.files import FileSource
from aidetector.adapters.sources.streams import StreamPool, StreamSource
from aidetector.bootstrap import build_source
from aidetector.configuration import SourceConfig


@pytest.mark.parametrize(
    "value", ["rtsp://camera/live.mp4", "0", "https://camera/stream"]
)
def test_live_source_classification_is_independent_of_the_url_suffix(tmp_path, value):
    config = SourceConfig.model_validate({"source": value})
    source = build_source(config, tmp_path, StreamPool())
    assert isinstance(source, StreamSource)
    assert source.sources == (value,)


def test_relative_file_paths_resolve_from_config_without_changing_cwd(tmp_path):
    config = SourceConfig.model_validate({"source": "clips/video.mp4"})
    source = build_source(config, tmp_path, StreamPool())
    assert isinstance(source, FileSource)
    assert source.sources == (str(tmp_path / "clips/video.mp4"),)


@pytest.mark.parametrize(
    "name",
    [
        "camera#1.png",
        pytest.param(
            "camera?1.png",
            marks=pytest.mark.skipif(
                sys.platform == "win32", reason="Windows filenames cannot contain '?'"
            ),
        ),
    ],
)
def test_local_image_names_are_not_parsed_as_urls(tmp_path, name):
    path = tmp_path / name
    assert cv2.imwrite(str(path), np.zeros((8, 8, 3), dtype=np.uint8))
    config = SourceConfig.model_validate({"source": name})
    source = build_source(config, tmp_path, StreamPool())
    batches = list(source.batches())
    assert list(batches[0].frames) == [str(path)]
    assert batches[1].finished_sources == (str(path),)


def test_capture_initialization_failure_is_reconnectable_and_stop_is_interruptible(
    monkeypatch,
):
    attempted = Event()

    def unavailable(*args):
        attempted.set()
        raise cv2.error("camera backend unavailable")

    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.cv2.VideoCapture", unavailable
    )
    streams = StreamPool()
    source = streams.subscribe(("0",))
    with streams.open(), ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(lambda: list(source.batches()))
        try:
            assert attempted.wait(2)
        finally:
            source.close()
        assert task.result(timeout=2) == []


def test_partial_capture_startup_stops_the_threads_that_already_started(monkeypatch):
    threads = []

    def unavailable(*args):
        raise cv2.error("camera backend unavailable")

    def cannot_start():
        raise RuntimeError("Cannot start another capture thread")

    def create_thread(**kwargs):
        thread = Thread(**kwargs)
        if threads:
            monkeypatch.setattr(thread, "start", cannot_start)
        threads.append(thread)
        return thread

    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.cv2.VideoCapture", unavailable
    )
    monkeypatch.setattr("aidetector.adapters.sources.streams.Thread", create_thread)
    streams = StreamPool()
    source = streams.subscribe(("rtsp://first", "rtsp://second"))
    with pytest.raises(RuntimeError, match="Cannot start another capture thread"):
        with streams.open():
            next(source.batches())
    assert not threads[0].is_alive(), "Partial startup left a capture thread alive"


def test_concurrent_capture_failures_are_all_reported(monkeypatch, caplog):
    started = Barrier(2)

    def broken_capture(source):
        started.wait(timeout=5)
        raise TypeError(f"Capture {source} failed")

    monkeypatch.setattr(
        "aidetector.adapters.sources.streams.cv2.VideoCapture", broken_capture
    )
    streams = StreamPool()
    source = streams.subscribe(("0", "1"))
    with pytest.raises(TypeError, match="Capture [01] failed"), streams.open():
        next(source.batches())
    assert "Capture 0 failed" in caplog.text
    assert "Capture 1 failed" in caplog.text
