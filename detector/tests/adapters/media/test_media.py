import gc
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from weakref import ref

import cv2
import numpy as np
import pytest

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.media.images import (
    compress_jpeg,
    crop_observation,
    draw_boxes,
    encode_jpeg,
    shrink_image,
)
from aidetector.adapters.media.video import encode_video
from aidetector.domain.models import BoundingBox, DetectionEvent, Observation


def observation(*boxes):
    return Observation(
        datetime(2026, 1, 1),
        np.zeros((100, 160, 3), dtype=np.uint8),
        {"cow": 0.9},
        boxes=boxes,
    )


def event(color=0):
    image = np.full((8, 8, 3), color, dtype=np.uint8)
    return DetectionEvent("camera", (Observation(datetime(2026, 1, 1), image, {}),))


@pytest.fixture
def cropped_event():
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    best = Observation(
        datetime(2026, 1, 1),
        image,
        {"cow": 0.9},
        (BoundingBox(10, 10, 40, 40, "cow", 0.9),),
    )
    return DetectionEvent("camera", (best,))


def test_crop_union_and_plot_preserve_the_original_pixels():
    original = observation(BoundingBox(10, 20, 30, 40), BoundingBox(50, 5, 80, 70))
    assert original.enclosing_box == BoundingBox(10, 5, 80, 70)
    crop = crop_observation(original, padding=0, plot=False)
    assert crop.shape == (65, 116, 3)
    plotted = draw_boxes(original)
    assert np.any(plotted != original.image)
    assert not np.any(original.image)


@pytest.mark.parametrize(
    "label, confidence, text",
    [
        ("cow", 0.934, "cow 93%"),
        ("koe🐄", 0.9, "koe🐄 90%"),
        (None, 0.9, None),
        ("cow", None, None),
    ],
)
def test_annotations_preserve_read_only_pixels_and_use_no_external_fonts(
    monkeypatch, label, confidence, text
):
    from ultralytics.utils import plotting

    font_lookup = Mock()
    put_text = Mock(wraps=cv2.putText)
    monkeypatch.setattr(plotting, "check_font", font_lookup)
    monkeypatch.setattr(cv2, "putText", put_text)
    original = observation(BoundingBox(10, 20, 80, 70, label, confidence))
    original.image.flags.writeable = False

    rendered = draw_boxes(original)

    assert rendered.shape == original.image.shape
    assert rendered.dtype == original.image.dtype
    assert not np.any(original.image)
    assert np.any(np.all(rendered == (255, 0, 0), axis=2))
    assert [call.args[1] for call in put_text.call_args_list] == (
        [] if text is None else [text]
    )
    font_lookup.assert_not_called()


@pytest.mark.parametrize(
    "box, clipped",
    [
        (BoundingBox(-10, -20, 30, 40), BoundingBox(0, 0, 30, 40)),
        (BoundingBox(150, 80, 180, 120), BoundingBox(150, 80, 159, 99)),
    ],
)
def test_annotations_clip_boxes_to_image_bounds(box, clipped):
    assert np.array_equal(
        draw_boxes(observation(box)), draw_boxes(observation(clipped))
    )


def test_empty_reversed_and_fully_outside_boxes_leave_pixels_unchanged():
    original = observation(
        BoundingBox(20, 20, 20, 40),
        BoundingBox(40, 40, 20, 20),
        BoundingBox(-20, -20, -1, -1),
        BoundingBox(170, 110, 190, 130),
    )
    assert np.array_equal(draw_boxes(original), original.image)


def test_images_without_boxes_do_not_import_inference_or_copy_pixels(tmp_path):
    script = """
import sys
from datetime import datetime
import numpy as np
from aidetector.adapters.media.images import draw_boxes
from aidetector.domain.models import Observation
image = np.zeros((8, 8, 3), dtype=np.uint8)
assert draw_boxes(Observation(datetime(2026, 1, 1), image, {})) is image
assert 'ultralytics' not in sys.modules
assert 'torch' not in sys.modules
"""
    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr


def test_shrink_does_not_upscale_and_uses_even_dimensions():
    image = np.zeros((101, 401, 3), dtype=np.uint8)
    shrunk = shrink_image(image, 200)
    assert shrunk.shape == (50, 200, 3)
    assert shrink_image(shrunk, 400) is shrunk


def test_video_with_identical_timestamps_is_encodable(tmp_path):
    encoded = encode_video(
        (observation(), observation()), width=None, crf=28, padding=0.1
    )
    path = tmp_path / "event.mp4"
    path.write_bytes(encoded)
    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FPS) == 1
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 2
    finally:
        capture.release()


def test_video_boxes_move_between_evaluated_frames(monkeypatch):
    drawn = []

    def record(observation, *, plot_boxes, **_options):
        drawn.append([(box.x1, box.x2, box.label) for box in plot_boxes])
        return observation.image

    monkeypatch.setattr("aidetector.adapters.media.video.crop_observation", record)
    started = datetime(2026, 1, 1)
    first = BoundingBox(0, 0, 10, 10, "cow", 0.9)
    second = BoundingBox(40, 0, 50, 10, "cow", 0.8)
    other = BoundingBox(100, 0, 110, 10, "calf", 0.7)

    def frame(seconds, *boxes, scored=True):
        return Observation(
            started + timedelta(seconds=seconds),
            np.zeros((20, 160, 3), dtype=np.uint8),
            {"cow": 0.9} if scored else {},
            boxes=boxes,
        )

    # Frames between evaluations carry the boxes of the next evaluated frame.
    encode_video(
        (
            frame(0, first, scored=False),
            frame(0.25, first),
            frame(0.5, second, other, scored=False),
            frame(1, second, other),
            frame(1.5, scored=False),
        ),
        width=None,
        crf=28,
        padding=0,
    )
    assert drawn == [
        [(0, 10, "cow")],
        [(0, 10, "cow")],
        [(13, 23, "cow"), (100, 110, "calf")],
        [(40, 50, "cow"), (100, 110, "calf")],
        [],
    ]


def test_impossible_image_size_is_an_explicit_error():
    with pytest.raises(MediaError, match="cannot fit"):
        compress_jpeg(observation().image, 1)


def test_ffmpeg_that_cannot_start_is_a_media_error(monkeypatch):
    monkeypatch.setattr(
        "aidetector.adapters.media.video.get_ffmpeg_exe", lambda: "/nonexistent/ffmpeg"
    )
    with pytest.raises(MediaError, match="could not finish"):
        encode_video((observation(),), width=None, crf=28, padding=0.1)


def test_ffmpeg_discovery_failure_is_a_media_error(monkeypatch):
    def unavailable():
        raise RuntimeError("No ffmpeg exe could be found")

    monkeypatch.setattr("aidetector.adapters.media.video.get_ffmpeg_exe", unavailable)
    with pytest.raises(MediaError, match="FFmpeg is unavailable") as error:
        encode_video((observation(),), width=None, crf=28, padding=0.1)
    assert isinstance(error.value.__cause__, RuntimeError)


def test_preferred_aspect_ratio_never_cuts_off_the_detected_region():
    original = observation(BoundingBox(20, 0, 140, 100))
    crop = crop_observation(original, padding=0, plot=False)
    assert crop.shape == (100, 160, 3)


@pytest.mark.parametrize("limit", [600, 1])
def test_video_size_limit_reuses_the_input_and_bounds_encoding_attempts(
    monkeypatch, limit
):
    attempts, inputs = [], []

    def encode(command, *, stdin, **kwargs):
        scale = command[command.index("-vf") + 1]
        width = int(scale.split("=")[1].split(":")[0])
        attempts.append(width)
        inputs.append(stdin.read())
        Path(command[-1]).write_bytes(b"x" * (width * 3))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("aidetector.adapters.media.video.subprocess.run", encode)
    frame = Observation(
        datetime(2026, 1, 1), np.zeros((240, 320, 3), dtype=np.uint8), {}
    )
    if limit == 1:
        with pytest.raises(MediaError, match="cannot fit"):
            encode_video((frame,), width=None, crf=28, padding=0.1, data_max=limit)
    else:
        assert (
            len(encode_video((frame,), width=None, crf=28, padding=0.1, data_max=limit))
            <= limit
        )
    assert 1 < len(attempts) < 20
    assert attempts[-1] < attempts[0]
    assert all(raw == frame.image.tobytes() for raw in inputs)


def test_video_temporary_storage_errors_are_media_failures(monkeypatch):
    def unavailable(**kwargs):
        raise PermissionError("Temporary storage is read-only")

    monkeypatch.setattr(
        "aidetector.adapters.media.video.tempfile.TemporaryDirectory", unavailable
    )
    with pytest.raises(MediaError, match="Cannot prepare or read video data") as error:
        encode_video((observation(),), width=None, crf=28, padding=0.1)
    assert isinstance(error.value.__cause__, PermissionError)


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
    settings = {"width": 1280, "crf": 28, "padding": 0.1}
    first, second = event(10), event(20)
    assert (
        media.video(first, **settings)
        == media.video(first, **settings, data_max=10)
        == b"first"
    )
    assert media.video(second, **settings) == b"second"
    del first
    gc.collect()
    assert media.video(second, **settings, data_max=10) == b"second"
    assert encoder.call_count == 2
