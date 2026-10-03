import logging
from collections import deque
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from threading import Condition, Event, Thread
from time import monotonic
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.diagnostics import resource_label
from aidetector.adapters.media.images import even_width, shrink_image
from aidetector.adapters.operational_status import source_key
from aidetector.application.ports import SourceBatch, SourceError
from aidetector.application.status import (
    ReportStatus,
    StatusEvent,
    ignore_status,
)
from aidetector.domain.models import CaptureStamp, Frame

logger = logging.getLogger(__name__)
_CAPTURE_TIMEOUT_MS = 10000
_CONTINUITY_GAP_SECONDS = 5


class CapturedFrame:
    """Lazily resize one decoded frame for its subscribers, once per width.

    Only the camera's capture thread accesses this cache. Subscribers retain
    immutable frames, not the cache, so variants live only as long as needed.
    """

    def __init__(self, frame: Frame):
        frame.image.setflags(write=False)
        self.original = frame
        self._sizes: dict[int, Frame] = {}

    def at_width(self, width: int) -> Frame:
        width = even_width(width)
        if self.original.image.shape[1] <= width:
            return self.original
        if width not in self._sizes:
            image = shrink_image(self.original.image, width)
            image.setflags(write=False)
            self._sizes[width] = replace(self.original, image=image)
        return self._sizes[width]


class _CaptureSession:
    """Stamp decoded frames; lost timing or geometry starts a new epoch."""

    def __init__(self, source: str, report_status: ReportStatus):
        self.source = source
        self.report_status = report_status
        self._shape: tuple[int, ...] | None = None
        self._epoch = ""
        self._sequence = 0
        self._previous_read: tuple[datetime, float] | None = None

    def frame(self, image: NDArray[np.uint8], sampled_at: float) -> CapturedFrame:
        date = datetime.now()
        interrupted = False
        if self._previous_read is not None:
            previous_date, previous_time = self._previous_read
            interrupted = not (
                0 <= sampled_at - previous_time <= _CONTINUITY_GAP_SECONDS
                and 0
                <= (date - previous_date).total_seconds()
                <= _CONTINUITY_GAP_SECONDS
            )
        if image.shape != self._shape or interrupted:
            self._shape = image.shape
            self._epoch, self._sequence = uuid4().hex, 0
            self.report_status(
                StatusEvent("source_epoch", self.source, source_epoch=self._epoch)
            )
        stamp = CaptureStamp(self._epoch, self._sequence, sampled_at)
        self._sequence += 1
        self._previous_read = date, sampled_at
        return CapturedFrame(Frame(date, image, stamp))


class StreamSource:
    """One detector's bounded subscription to shared live captures."""

    def __init__(
        self,
        sources: tuple[str, ...],
        width: int = 1280,
        retention: int = 15,
        interval: float = 0,
    ):
        self.sources = sources
        self.width = width
        self.retention = retention
        self.interval = interval
        self._condition = Condition()
        self._frames: dict[str, deque[Frame]] = {}
        self._next_sample = dict.fromkeys(sources, 0.0)
        self._epochs: dict[str, str] = {}
        self._closed = False
        self._error: Exception | None = None

    def publish(self, source: str, frame: CapturedFrame, sampled_at: float) -> None:
        with self._condition:
            if self._closed:
                return
            capture = frame.original.capture
            if capture is not None and capture.epoch != self._epochs.get(source):
                self._epochs[source] = capture.epoch
                self._frames.pop(source, None)
                self._next_sample[source] = 0.0
            if sampled_at < self._next_sample[source]:
                return
            self._next_sample[source] = sampled_at + self.interval
            self._frames.setdefault(source, deque(maxlen=self.retention)).append(
                frame.at_width(self.width)
            )
            self._condition.notify()

    def fail(self, error: Exception) -> None:
        with self._condition:
            if self._error is None:
                self._error = error
            self._condition.notify_all()

    def batches(self) -> Generator[SourceBatch, None, None]:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: (
                            bool(self._frames)
                            or self._closed
                            or self._error is not None
                        ),
                        timeout=0.5,
                    )
                    if self._error is not None:
                        raise self._error
                    if self._closed:
                        return
                    snapshot = {
                        source: tuple(frames) for source, frames in self._frames.items()
                    }
                    self._frames.clear()
                advance_to = max(
                    (frames[-1].date for frames in snapshot.values()),
                    default=datetime.now(),
                )
                yield SourceBatch(snapshot, advance_to)
        finally:
            self.close()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._frames.clear()
            self._condition.notify_all()


class StreamPool:
    """Own one capture per source. Register subscriptions before opening the pool."""

    def __init__(self, report_status: ReportStatus = ignore_status):
        self.report_status = report_status
        self._subscribers: dict[str, list[StreamSource]] = {}
        self._stop = Event()
        self._threads: list[Thread] = []

    def subscribe(
        self,
        sources: tuple[str, ...],
        width: int = 1280,
        retention: int = 15,
        interval: float = 0,
    ) -> StreamSource:
        subscription = StreamSource(sources, width, retention, interval)
        for source in sources:
            self._subscribers.setdefault(source, []).append(subscription)
        return subscription

    @contextmanager
    def open(self) -> Iterator[None]:
        try:
            for index, source in enumerate(self._subscribers):
                thread = Thread(
                    target=self._supervise_capture,
                    args=(index, source),
                    name=f"capture-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            yield
        finally:
            self.close()

    def _supervise_capture(self, index: int, source: str) -> None:
        try:
            self._capture(index, source)
        except Exception as error:
            logger.exception("Stream %d capture worker failed", index + 1)
            for subscriber in self._subscribers[source]:
                subscriber.fail(error)

    def _capture(self, index: int, source: str) -> None:
        identity = source_key(source)[:12]
        attempt = 0
        while not self._stop.is_set():
            capture = None
            started = monotonic()
            attempt += 1
            try:
                logger.info(
                    "Stream %d [%s]: opening %s for %d detector(s); attempt=%d; open/read timeout=%s",
                    index + 1,
                    identity,
                    resource_label(source),
                    len(self._subscribers[source]),
                    attempt,
                    "backend default"
                    if source.isdecimal()
                    else f"{_CAPTURE_TIMEOUT_MS}ms",
                )
                capture = (
                    cv2.VideoCapture(int(source))
                    if source.isdecimal()
                    else cv2.VideoCapture(
                        source,
                        cv2.CAP_FFMPEG,
                        [
                            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                            _CAPTURE_TIMEOUT_MS,
                            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                            _CAPTURE_TIMEOUT_MS,
                            # Frame-threaded decoding buffers frames before returning
                            # them. Live cameras need low latency over batch throughput.
                            cv2.CAP_PROP_N_THREADS,
                            1,
                        ],
                    )
                )
                if not capture.isOpened():
                    self.report_status(
                        StatusEvent(
                            "offline",
                            source,
                            "Camera could not be reached. Reconnecting…",
                        )
                    )
                    logger.warning(
                        "Stream %d [%s] could not be opened after %.2fs; reconnecting",
                        index + 1,
                        identity,
                        monotonic() - started,
                    )
                else:
                    first_frame = True
                    session = _CaptureSession(source, self.report_status)
                    measured_at = monotonic()
                    reads = 0
                    read_seconds = publish_seconds = 0.0
                    while not self._stop.is_set():
                        read_started = monotonic()
                        available, image = capture.read()
                        sampled_at = monotonic()
                        if not available:
                            self.report_status(
                                StatusEvent(
                                    "offline",
                                    source,
                                    "Camera connection was lost. Reconnecting…",
                                )
                            )
                            logger.warning(
                                "Stream %d [%s] disconnected after %.2fs; reconnecting",
                                index + 1,
                                identity,
                                monotonic() - started,
                            )
                            break
                        if first_frame:
                            logger.info(
                                "Stream %d [%s] connected in %.2fs: receiving %dx%d frames; dtype=%s",
                                index + 1,
                                identity,
                                monotonic() - started,
                                image.shape[1],
                                image.shape[0],
                                image.dtype,
                            )
                            first_frame = False
                        frame = session.frame(image, sampled_at)
                        self.report_status(StatusEvent("frame", source))
                        for subscriber in self._subscribers[source]:
                            subscriber.publish(source, frame, sampled_at)
                        published_at = monotonic()
                        reads += 1
                        read_seconds += sampled_at - read_started
                        publish_seconds += published_at - sampled_at
                        if published_at - measured_at >= 30:
                            logger.info(
                                "Stream %d [%s]: %.1f decoded frames/s; "
                                "read (including camera wait)=%.1fms/frame; "
                                "resize/publish=%.1fms/frame",
                                index + 1,
                                identity,
                                reads / (published_at - measured_at),
                                read_seconds * 1000 / reads,
                                publish_seconds * 1000 / reads,
                            )
                            measured_at = published_at
                            reads = 0
                            read_seconds = publish_seconds = 0.0
            except cv2.error as error:
                self.report_status(
                    StatusEvent(
                        "offline", source, "Camera could not be read. Reconnecting…"
                    )
                )
                logger.warning(
                    "Stream %d [%s] capture failed: OpenCV code=%s, function=%s, reason=%s; reconnecting",
                    index + 1,
                    identity,
                    error.code,
                    error.func,
                    error.err,
                )
            finally:
                if capture is not None:
                    capture.release()
            self._stop.wait(1)
        logger.info("Stream %d [%s] stopped", index + 1, identity)

    def close(self) -> None:
        self._stop.set()
        for subscribers in self._subscribers.values():
            for subscriber in subscribers:
                subscriber.close()
        deadline = monotonic() + _CAPTURE_TIMEOUT_MS / 1000 + 2
        for index, thread in enumerate(self._threads):
            thread.join(timeout=max(0, deadline - monotonic()))
            if thread.is_alive():
                raise SourceError(
                    f"Stream {index + 1} did not stop within the capture timeout"
                )
