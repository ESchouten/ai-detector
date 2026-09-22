import gc
from datetime import datetime
from unittest.mock import Mock
from weakref import ref

import numpy as np
import pytest

from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.media.images import compress_jpeg, encode_jpeg
from aidetector.domain.models import BoundingBox, DetectionEvent, Observation


def event(color=0):
    image = np.full((8, 8, 3), color, dtype=np.uint8)
    return DetectionEvent("camera", (Observation(datetime(2026, 1, 1), image, {}),))


@pytest.fixture
def cropped_event():
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    observation = Observation(
        datetime(2026, 1, 1),
        image,
        {"cow": 0.9},
        (BoundingBox(10, 10, 40, 40, "cow", 0.9),),
    )
    return DetectionEvent("camera", (observation,))


def test_media_cache_does_not_keep_a_completed_event_or_its_pixels_alive():
    media = EventMedia()
    current = event()
    event_reference = ref(current)
    image_reference = ref(current.best.image)
    assert media.image(current, "original").startswith(b"\xff\xd8")

    del current
    gc.collect()

    assert event_reference() is None
    assert image_reference() is None


def test_encodings_are_shared_within_an_event_and_replaced_for_the_next_one(
    monkeypatch,
):
    encodings = []

    def encode(image):
        encodings.append(int(image[0, 0, 0]))
        return bytes([image[0, 0, 0]])

    monkeypatch.setattr("aidetector.adapters.media.event_media.encode_jpeg", encode)
    media = EventMedia()
    first, second = event(10), event(20)
    assert media.image(first, "original") == media.image(first, "original") == b"\x0a"
    assert media.image(second, "original") == b"\x14"
    del first
    gc.collect()
    assert media.image(second, "original") == b"\x14"
    assert encodings == [10, 20]


@pytest.mark.parametrize("kind", ["original", "annotated"])
@pytest.mark.parametrize("max_bytes", [None, 10_000])
def test_uncropped_images_reuse_encoding_when_only_crop_options_change(
    monkeypatch, cropped_event, kind, max_bytes
):
    encoder = Mock(wraps=encode_jpeg if max_bytes is None else compress_jpeg)
    monkeypatch.setattr(
        "aidetector.adapters.media.event_media."
        + ("encode_jpeg" if max_bytes is None else "compress_jpeg"),
        encoder,
    )
    media = EventMedia()
    images = [
        media.image(cropped_event, kind, padding=0.1, data_max=max_bytes),
        media.image(cropped_event, kind, padding=0.3, data_max=max_bytes),
        media.image(
            cropped_event, kind, padding=0.3, data_max=max_bytes, plot_crop=False
        ),
    ]
    assert images[0] == images[1] == images[2]
    assert images[0].startswith(b"\xff\xd8")
    assert encoder.call_count == 1


def test_crops_keep_padding_and_annotation_variants_distinct(
    monkeypatch, cropped_event
):
    encoder = Mock(wraps=encode_jpeg)
    monkeypatch.setattr("aidetector.adapters.media.event_media.encode_jpeg", encoder)
    media = EventMedia()
    variants = [(0.1, True), (0.3, True), (0.3, False)]
    images = [
        media.image(cropped_event, "crop", padding=padding, plot_crop=plot)
        for padding, plot in variants
    ]
    assert len(set(images)) == 3
    for (padding, plot), image in zip(variants, images, strict=True):
        assert (
            media.image(cropped_event, "crop", padding=padding, plot_crop=plot) == image
        )
    assert encoder.call_count == 3


def test_video_cache_reuses_compatible_limits_and_changes_with_the_event(monkeypatch):
    encoder = Mock(side_effect=[b"first", b"second"])
    monkeypatch.setattr("aidetector.adapters.media.event_media.encode_video", encoder)
    media = EventMedia()
    first, second = event(10), event(20)
    assert media.video(first) == media.video(first, data_max=10) == b"first"
    assert media.video(second) == b"second"
    del first
    gc.collect()
    assert media.video(second, data_max=10) == b"second"
    assert encoder.call_count == 2
