import logging
from collections import deque
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import Condition, Event, Thread
from time import monotonic

import cv2

from aidetector.adapters.media.images import shrink_image
from aidetector.application.ports import SourceBatch, SourceError
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.domain.models import Frame

logger = logging.getLogger(__name__)
_CAPTURE_TIMEOUT_MS = 10000


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
        self._closed = False
        self._error: Exception | None = None

    def publish(self, source: str, frame: Frame, sampled_at: float) -> None:
        with self._condition:
            if self._closed or sampled_at < self._next_sample[source]:
                return
            self._next_sample[source] = sampled_at + self.interval
            image = shrink_image(frame.image, self.width)
            image.setflags(write=False)
            self._frames.setdefault(source, deque(maxlen=self.retention)).append(
                Frame(frame.date, image)
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
        while not self._stop.is_set():
            capture = None
            try:
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
                        "Stream %d could not be opened; reconnecting", index + 1
                    )
                else:
                    while not self._stop.is_set():
                        available, image = capture.read()
                        if not available:
                            self.report_status(
                                StatusEvent(
                                    "offline",
                                    source,
                                    "Camera connection was lost. Reconnecting…",
                                )
                            )
                            logger.warning(
                                "Stream %d disconnected; reconnecting", index + 1
                            )
                            break
                        sampled_at = monotonic()
                        image.setflags(write=False)
                        frame = Frame(datetime.now(), image)
                        self.report_status(StatusEvent("frame", source))
                        for subscriber in self._subscribers[source]:
                            subscriber.publish(source, frame, sampled_at)
            except cv2.error:
                self.report_status(
                    StatusEvent(
                        "offline", source, "Camera could not be read. Reconnecting…"
                    )
                )
                logger.warning("Stream %d capture failed; reconnecting", index + 1)
            finally:
                if capture is not None:
                    capture.release()
            self._stop.wait(1)

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
