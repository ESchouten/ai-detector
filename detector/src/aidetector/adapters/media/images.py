"""Resize, annotate, crop, and encode observation images."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.media import MediaError
from aidetector.domain.models import BoundingBox, Observation

Image = NDArray[np.uint8]


def even_width(value: int) -> int:
    return max(2, value // 2 * 2)


def shrink_image(image: Image, width_max: int) -> Image:
    height, width = image.shape[:2]
    width_max = even_width(width_max)
    if width <= width_max:
        return image
    height_max = even_width(round(height * width_max / width))
    return cv2.resize(image, (width_max, height_max), interpolation=cv2.INTER_AREA)


def encode_jpeg(image: Image, quality: int = 95) -> bytes:
    try:
        success, encoded = cv2.imencode(
            ".jpg", image, (cv2.IMWRITE_JPEG_QUALITY, quality)
        )
    except cv2.error as error:
        raise MediaError("JPEG encoding failed") from error
    if not success:
        raise MediaError("JPEG encoding failed")
    return encoded.tobytes()


def draw_boxes(
    observation: Observation, boxes: Sequence[BoundingBox] | None = None
) -> Image:
    boxes = observation.boxes if boxes is None else boxes
    if not boxes:
        return observation.image

    from ultralytics.utils.plotting import Annotator

    image = observation.image.copy()
    height, width = image.shape[:2]
    # Keep OpenCV drawing; non-ASCII constructor examples trigger font lookup.
    annotator = Annotator(image, pil=False)
    for box in boxes:
        x1, y1 = max(0, box.x1), max(0, box.y1)
        x2, y2 = min(width - 1, box.x2), min(height - 1, box.y2)
        if x2 <= x1 or y2 <= y1:
            continue
        label = (
            f"{box.label} {box.confidence:.0%}"
            if box.label is not None and box.confidence is not None
            else ""
        )
        annotator.box_label((x1, y1, x2, y2), label, color=(255, 0, 0))
    return image


def _centered_range(center: float, size: int, limit: int) -> tuple[int, int]:
    size = max(1, min(size, limit))
    start = max(0, min(round(center - size / 2), limit - size))
    return start, start + size


def crop_observation(
    observation: Observation,
    region: BoundingBox | None = None,
    aspect_ratio: float | None = 16 / 9,
    padding: float = 0.1,
    plot: bool = True,
    plot_boxes: Sequence[BoundingBox] | None = None,
) -> Image | None:
    region = region or observation.enclosing_box
    if region is None:
        return None
    image = draw_boxes(observation, plot_boxes) if plot else observation.image
    height, width = image.shape[:2]
    pad_x = round(max(1, region.x2 - region.x1) * padding)
    pad_y = round(max(1, region.y2 - region.y1) * padding)
    x1, y1 = max(0, region.x1 - pad_x), max(0, region.y1 - pad_y)
    x2, y2 = min(width, region.x2 + pad_x), min(height, region.y2 + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    if aspect_ratio is not None:
        target_width, target_height = x2 - x1, y2 - y1
        if target_width / target_height < aspect_ratio:
            target_width = round(target_height * aspect_ratio)
        else:
            target_height = round(target_width / aspect_ratio)
        # Clamp each dimension independently: fitting the preferred aspect ratio
        # must not cut away part of the detection when the image is too narrow.
        x1, x2 = _centered_range((x1 + x2) / 2, target_width, width)
        y1, y2 = _centered_range((y1 + y2) / 2, target_height, height)
    return image[y1:y2, x1:x2]


def compress_jpeg(image: Image, max_bytes: int) -> bytes:
    for quality in range(90, 9, -10):
        encoded = encode_jpeg(image, quality)
        if len(encoded) <= max_bytes:
            return encoded
    original_height, original_width = image.shape[:2]
    for percent in range(90, 9, -10):
        resized = cv2.resize(
            image,
            (
                max(1, original_width * percent // 100),
                max(1, original_height * percent // 100),
            ),
            interpolation=cv2.INTER_AREA,
        )
        encoded = encode_jpeg(resized, 10)
        if len(encoded) <= max_bytes:
            return encoded
    raise MediaError("JPEG cannot fit the configured size limit")
