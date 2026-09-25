import logging
import math
from collections.abc import Generator
from datetime import datetime, timedelta
from threading import Event
from urllib.parse import urlsplit

import cv2

from aidetector.adapters.media.images import shrink_image
from aidetector.application.ports import SourceBatch, SourceError
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import source_kind
from aidetector.domain.models import Frame

logger = logging.getLogger(__name__)


class FileSource:
    def __init__(
        self,
        sources: tuple[str, ...],
        width: int = 1280,
        interval: float = 0,
        started_at: datetime | None = None,
        report_status: ReportStatus = ignore_status,
    ):
        self.sources = sources
        self.width = width
        self.interval = interval
        self.started_at = started_at
        self.report_status = report_status
        self._stop = Event()

    def batches(self) -> Generator[SourceBatch, None, None]:
        for index, source in enumerate(self.sources):
            if self._stop.is_set():
                return
            logger.info("Reading file source %d/%d", index + 1, len(self.sources))
            started_at = self.started_at or datetime.now()
            if source_kind(source) == "image":
                image = cv2.imread(source)
                if image is None:
                    raise SourceError(f"Cannot read image source {index + 1}")
                self.report_status(StatusEvent("frame", source))
                yield SourceBatch(
                    {source: (Frame(started_at, shrink_image(image, self.width)),)}
                )
            else:
                yield from self._video(source, index, started_at)
            logger.info("Finished file source %d/%d", index + 1, len(self.sources))
            yield SourceBatch({}, finished_sources=(source,))

    def _video(
        self, source: str, index: int, started_at: datetime
    ) -> Generator[SourceBatch, None, None]:
        capture = (
            cv2.VideoCapture(
                source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    5000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    5000,
                ],
            )
            if urlsplit(source).scheme in {"http", "https"}
            else cv2.VideoCapture(source)
        )
        try:
            if not capture.isOpened():
                raise SourceError(f"Cannot open video source {index + 1}")
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                raise SourceError(f"Video source {index + 1} has no valid frame rate")
            frame_index = 0
            next_sample = timedelta(0)
            while not self._stop.is_set():
                available, image = capture.read()
                if not available:
                    return
                elapsed = timedelta(seconds=frame_index / fps)
                frame_index += 1
                if elapsed < next_sample:
                    continue
                next_sample = elapsed + timedelta(seconds=self.interval)
                frame = Frame(
                    started_at + elapsed,
                    shrink_image(image, self.width),
                )
                self.report_status(StatusEvent("frame", source))
                yield SourceBatch({source: (frame,)})
        finally:
            capture.release()

    def close(self) -> None:
        self._stop.set()
