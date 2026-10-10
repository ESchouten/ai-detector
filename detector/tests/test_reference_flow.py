import json
from datetime import datetime

import cv2
import pytest

from aidetector.adapters.exporters.archive_metadata import EventMetadata
from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.sources.files import FileSource
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.configuration import DiskConfig
from aidetector.domain.models import (
    BoundingBox,
    Observation,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, EventPolicy, ExportPolicy
from tests.support.media import write_video


class ScheduledDetector:
    def __init__(self):
        self.frame_index = 0

    def detect(self, sources):
        outputs = {}
        for source, frames in sources.items():
            frame = frames[-1]
            matching = self.frame_index in (1, 2, 3)
            scores = {"cow": 0.8 + self.frame_index * 0.05} if matching else {}
            boxes = (
                (BoundingBox(8, 8, 24, 32, "cow", scores["cow"]),) if matching else ()
            )
            outputs[source] = (
                Observation(frame.date, frame.image, scores, boxes=boxes),
            )
            self.frame_index += 1
        return outputs


class ApprovingValidator:
    def validate(self, event):
        return ValidationResult(ValidationStatus.APPROVED)


@pytest.mark.parametrize("category", [None, "Camera 1"])
def test_video_to_validated_archive_uses_real_media_and_flushes_at_eof(
    tmp_path, category
):
    video = tmp_path / "input.avi"
    write_video(video)
    source = FileSource((str(video),), started_at=datetime(2026, 1, 1))
    pipeline = DetectionPipeline(
        ScheduledDetector(),
        EventPolicy(min_frames=3, inactivity_timeout=2, trailing_time=0.2),
    )
    root = tmp_path / "detections"
    exporter = DiskExporter(DiskConfig(directory=category), root, EventMedia())
    delivery = EventDelivery(
        (Destination("disk", exporter, ExportPolicy()),),
        Cooldown(),
        ApprovingValidator(),
    )
    completed = []
    try:
        for batch in source.batches():
            completed.extend(pipeline.process(batch))
    finally:
        source.close()
    assert pipeline.finish() == []
    assert len(completed) == 1
    assert delivery.deliver(completed[0]).delivered == ("disk",)

    category_path = root / (category or "cow")
    [directory] = list((category_path / "approved").iterdir())
    assert list(root.glob("*/approved/*/metadata.json")) == [
        directory / "metadata.json"
    ]
    metadata = json.loads((directory / "metadata.json").read_text())
    assert metadata["validated"] is True
    assert metadata["detections"] == 5
    assert metadata["duration"] == 0.4
    assert metadata["confidence"] == pytest.approx(0.95)
    assert metadata["timestamp"] == directory.name
    assert metadata["start"] == "2026-01-01T00:00:00.100000"
    assert metadata["end"] == "2026-01-01T00:00:00.500000"
    assert metadata["crop"] == {"x1": 8, "y1": 8, "x2": 24, "y2": 32}
    EventMetadata.model_validate(metadata)
    assert cv2.imread(str(directory / "best.jpg")).shape == (48, 64, 3)
    assert cv2.imread(str(directory / "clean.jpg")).shape == (48, 64, 3)
    capture = cv2.VideoCapture(str(directory / "video.mp4"))
    try:
        assert capture.isOpened()
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 5
        assert capture.read()[0]
    finally:
        capture.release()
    assert list((category_path / ".pending").iterdir()) == []


def test_no_yolo_flow_archives_unclassified_frames_without_overwriting(tmp_path):
    video = tmp_path / "input.avi"
    write_video(video, frames=1)
    source = FileSource((str(video),), started_at=datetime(2026, 1, 1))
    pipeline = DetectionPipeline()
    batch = next(source.batches())
    [event] = pipeline.process(batch)
    root = tmp_path / "detections"
    delivery = EventDelivery(
        (
            Destination(
                "disk", DiskExporter(DiskConfig(), root, EventMedia()), ExportPolicy()
            ),
        ),
        Cooldown(),
    )
    assert delivery.deliver(event).delivered == ("disk",)
    assert delivery.deliver(event).delivered == ("disk",)
    directories = sorted((root / "unclassified" / "unvalidated").iterdir())
    assert len(directories) == 2
    assert directories[0].name != directories[1].name
    for directory in directories:
        metadata = json.loads((directory / "metadata.json").read_text())
        assert metadata["validated"] is None
        assert metadata["confidences"] == {}
        assert metadata["timestamp"] == directory.name


def test_each_file_flushes_before_the_next_file_is_read(tmp_path):
    first, second = tmp_path / "first.avi", tmp_path / "second.avi"
    write_video(first, frames=4)
    write_video(second, frames=4)
    source = FileSource((str(first), str(second)))
    pipeline = DetectionPipeline(ScheduledDetector(), EventPolicy(min_frames=3))
    ended = []
    for batch in source.batches():
        if str(second) in batch.frames:
            assert ended == [str(first)]
        ended.extend(event.source for event in pipeline.process(batch))
    assert ended == [str(first)]
    assert pipeline.finish() == []
