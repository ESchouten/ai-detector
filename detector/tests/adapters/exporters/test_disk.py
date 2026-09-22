import errno
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from aidetector.adapters.exporters.archive_metadata import EventMetadata
from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.application.ports import DeliveryError
from aidetector.configuration import DiskConfig
from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Observation,
    ValidationResult,
    ValidationStatus,
)


def test_failed_archive_does_not_publish_partial_files(tmp_path, monkeypatch):
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8), {"cow": 0.9}
    )
    result = EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
    )
    media = EventMedia()

    def failed_video(*args, **kwargs):
        raise MediaError("Encoding failed")

    monkeypatch.setattr(media, "video", failed_video)
    exporter = DiskExporter(DiskConfig(strategy="ALL"), tmp_path, media)
    with pytest.raises(DeliveryError, match="Encoding failed"):
        exporter.export(result)
    assert list((tmp_path / "cow/unvalidated").iterdir()) == []
    assert list((tmp_path / "cow/.pending").iterdir()) == []


@pytest.mark.parametrize("collision", [errno.EEXIST, errno.ENOTEMPTY])
def test_archive_publication_retries_a_concurrent_timestamp_collision(
    tmp_path, monkeypatch, collision
):
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8), {"cow": 0.9}
    )
    result = EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
    )
    rename = Path.rename
    competing_archive = None

    def publish(path, target):
        nonlocal competing_archive
        if competing_archive is None:
            competing_archive = target
            target.mkdir()
            (target / "existing.txt").write_text("Existing archive")
            raise OSError(collision, "Destination already exists")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", publish)
    DiskExporter(DiskConfig(), tmp_path, EventMedia()).export(result)

    assert (competing_archive / "existing.txt").read_text() == "Existing archive"
    [metadata_path] = list(tmp_path.glob("cow/unvalidated/*/metadata.json"))
    metadata = EventMetadata.model_validate_json(metadata_path.read_text())
    assert metadata.timestamp == metadata_path.parent.name
    assert metadata.timestamp == "2026-01-01T00-00-00.000001"
    assert len(list((tmp_path / "cow/unvalidated").iterdir())) == 2
    assert list((tmp_path / "cow/.pending").iterdir()) == []


def test_archive_publication_failure_cleans_staging_and_reports_delivery_error(
    tmp_path, monkeypatch
):
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8), {"cow": 0.9}
    )
    result = EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
    )

    def cannot_publish(path, target):
        raise PermissionError(errno.EACCES, "Cannot publish archive")

    monkeypatch.setattr(Path, "rename", cannot_publish)
    with pytest.raises(DeliveryError, match="Cannot publish archive"):
        DiskExporter(DiskConfig(), tmp_path, EventMedia()).export(result)
    assert list((tmp_path / "cow/unvalidated").iterdir()) == []
    assert list((tmp_path / "cow/.pending").iterdir()) == []


@pytest.mark.parametrize(
    "status, stage, validated, error",
    [
        (ValidationStatus.APPROVED, "approved", True, None),
        (ValidationStatus.REJECTED, "rejected", False, None),
        (ValidationStatus.UNVALIDATED, "unvalidated", None, None),
        (ValidationStatus.FAILED, "unvalidated", None, "Verifier unavailable"),
    ],
)
def test_archive_preserves_public_stages_and_validation_metadata(
    tmp_path, status, stage, validated, error
):
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((8, 8, 3), dtype=np.uint8), {"cow": 0.9}
    )
    result = EventResult(
        DetectionEvent("camera", (observation,)), ValidationResult(status, error)
    )
    DiskExporter(DiskConfig(), tmp_path, EventMedia()).export(result)
    [metadata_path] = list(tmp_path.glob("cow/*/*/metadata.json"))
    assert metadata_path.parent.parent.name == stage
    metadata = EventMetadata.model_validate_json(metadata_path.read_text())
    assert metadata.validated is validated
    assert metadata.validation_error == error


def test_all_strategy_archives_every_frame_and_the_standard_event_files(tmp_path):
    started = datetime(2026, 1, 1)
    observations = tuple(
        Observation(
            started + timedelta(seconds=second),
            np.full((24, 32, 3), color, dtype=np.uint8),
            confidence,
        )
        for second, color, confidence in (
            (0, 0, {}),
            (0, 120, {"cow": 0.95}),
            (1, 240, {"cow": 0.8}),
        )
    )
    result = EventResult(
        DetectionEvent("camera", observations),
        ValidationResult(ValidationStatus.APPROVED),
    )

    DiskExporter(DiskConfig(strategy="ALL"), tmp_path, EventMedia()).export(result)

    [directory] = (tmp_path / "cow/approved").iterdir()
    frame_names = (
        "2026-01-01T00-00-00.000000_0.jpg",
        "2026-01-01T00-00-00.000000_1.jpg",
        "2026-01-01T00-00-01.000000_2.jpg",
    )
    assert {path.name for path in directory.iterdir()} == {
        *frame_names,
        "best.jpg",
        "clean.jpg",
        "video.mp4",
        "metadata.json",
    }
    for filename, observation in zip(frame_names, observations, strict=True):
        image = cv2.imread(str(directory / filename))
        assert np.array_equal(image, observation.image)
    assert np.array_equal(
        cv2.imread(str(directory / "clean.jpg")), result.event.best.image
    )
    assert cv2.imread(str(directory / "best.jpg")).shape == (24, 32, 3)
    metadata = EventMetadata.model_validate_json(
        (directory / "metadata.json").read_text()
    )
    assert metadata.timestamp == directory.name
    assert metadata.detections == 3
    assert metadata.confidences == {"cow": 0.95}
    assert metadata.duration == 1
    assert metadata.validated is True

    capture = cv2.VideoCapture(str(directory / "video.mp4"))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 3
        for expected in observations:
            success, image = capture.read()
            assert success
            assert image.shape == expected.image.shape
            assert float(image.mean()) == pytest.approx(expected.image.mean(), abs=3)
        assert not capture.read()[0]
    finally:
        capture.release()
    assert list((tmp_path / "cow/.pending").iterdir()) == []
