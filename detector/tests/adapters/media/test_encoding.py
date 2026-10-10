import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.images import (
    compress_jpeg,
    crop_observation,
    draw_boxes,
    shrink_image,
)
from aidetector.adapters.media.video import encode_video
from aidetector.domain.models import BoundingBox, Observation


def observation(*boxes):
    return Observation(
        datetime(2026, 1, 1),
        np.zeros((100, 160, 3), dtype=np.uint8),
        {"cow": 0.9},
        boxes=boxes,
    )


def test_crop_union_and_plot_preserve_the_original_pixels():
    original = observation(BoundingBox(10, 20, 30, 40), BoundingBox(50, 5, 80, 70))
    assert original.enclosing_box == BoundingBox(10, 5, 80, 70)
    crop = crop_observation(original, aspect_ratio=None, padding=0, plot=False)
    assert crop.shape == (65, 70, 3)
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
    encoded = encode_video((observation(), observation()))
    path = tmp_path / "event.mp4"
    path.write_bytes(encoded)
    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FPS) == 1
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 2
    finally:
        capture.release()


def test_impossible_image_size_is_an_explicit_error():
    with pytest.raises(MediaError, match="cannot fit"):
        compress_jpeg(observation().image, 1)


def test_ffmpeg_failure_is_not_reported_as_missing_optional_video(monkeypatch):
    monkeypatch.setattr(
        "aidetector.adapters.media.video.get_ffmpeg_exe", lambda: "/nonexistent/ffmpeg"
    )
    with pytest.raises(MediaError, match="could not finish"):
        encode_video((observation(),))


def test_ffmpeg_discovery_failure_is_a_media_error(monkeypatch):
    def unavailable():
        raise RuntimeError("No ffmpeg exe could be found")

    monkeypatch.setattr("aidetector.adapters.media.video.get_ffmpeg_exe", unavailable)
    with pytest.raises(MediaError, match="FFmpeg is unavailable") as error:
        encode_video((observation(),))
    assert isinstance(error.value.__cause__, RuntimeError)


def test_requested_aspect_ratio_never_cuts_off_the_detected_region():
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
            encode_video((frame,), data_max=limit)
    else:
        assert len(encode_video((frame,), data_max=limit)) <= limit
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
        encode_video((observation(),))
    assert isinstance(error.value.__cause__, PermissionError)
