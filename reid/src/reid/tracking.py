"""Cut unlabelled cow tracks out of farm video with a stock YOLO model and tracker.

Each track becomes its own provisional identity, so tracks can be clustered,
named by a person, or used as positives for self-supervised training.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from reid.manifest import Crop, lacks_colour

COCO_COW = 19


@dataclass(frozen=True)
class Detection:
    """One tracked animal in one frame, in pixel coordinates."""

    track: int
    x1: int
    y1: int
    x2: int
    y2: int
    outline: NDArray[np.float32] | None = None


def covered(box: Detection, others: Sequence[Detection]) -> float:
    """Share of the box hidden under other boxes, counting overlaps once."""
    area = (box.x2 - box.x1) * (box.y2 - box.y1)
    if area <= 0:
        return 1.0
    cover = np.zeros((box.y2 - box.y1, box.x2 - box.x1), dtype=bool)
    for other in others:
        if other is box:
            continue
        x1, y1 = max(other.x1, box.x1), max(other.y1, box.y1)
        x2, y2 = min(other.x2, box.x2), min(other.y2, box.y2)
        if x2 > x1 and y2 > y1:
            cover[y1 - box.y1 : y2 - box.y1, x1 - box.x1 : x2 - box.x1] = True
    return float(cover.mean())


def usable(
    detection: Detection,
    detections: Sequence[Detection],
    width: int,
    height: int,
    *,
    min_size: int,
    max_covered: float,
    edge: int = 2,
) -> bool:
    """Large, whole and mostly unobstructed: the crops worth learning from."""
    if min(detection.x2 - detection.x1, detection.y2 - detection.y1) < min_size:
        return False
    if (
        detection.x1 <= edge
        or detection.y1 <= edge
        or detection.x2 >= width - edge
        or detection.y2 >= height - edge
    ):
        return False
    return covered(detection, detections) <= max_covered


def cut(
    image: NDArray[np.uint8], detection: Detection, mask_background: bool
) -> NDArray[np.uint8]:
    """The box's pixels; with an outline, everything outside it is made gray.

    In a crowded alley a box holds parts of neighbours; the mask keeps the
    embedding about this cow.
    """
    import cv2

    crop = image[detection.y1 : detection.y2, detection.x1 : detection.x2].copy()
    if mask_background and detection.outline is not None and len(detection.outline):
        mask = np.zeros(crop.shape[:2], dtype=np.uint8)
        points = np.round(detection.outline - [detection.x1, detection.y1]).astype(
            np.int32
        )
        cv2.fillPoly(mask, [points], 255)
        crop[mask == 0] = 127
    return crop


def tracks_from_video(
    video: Path,
    out: Path,
    *,
    session: str,
    model: str = "yolo26x-seg.pt",
    every: int = 5,
    imgsz: int = 1280,
    confidence: float = 0.5,
    min_size: int = 128,
    max_covered: float = 0.3,
    min_crops: int = 3,
    mask_background: bool = True,
    tracker: str = "bytetrack.yaml",
    device: str | None = None,
) -> list[Crop]:
    """Track cows through a video and keep the usable crops of each track.

    Crops go to `<out>/<session>-<video>-<track>/<frame>.jpg`; the track name is
    also the provisional identity. Tracks with fewer than `min_crops` usable
    crops are dropped.
    """
    import cv2
    from ultralytics import YOLO

    detector = YOLO(model)
    by_track: dict[str, list[Crop]] = {}
    results = detector.track(
        source=str(video),
        stream=True,
        persist=True,
        classes=[COCO_COW],
        conf=confidence,
        imgsz=imgsz,
        vid_stride=every,
        tracker=tracker,
        device=device,
        verbose=False,
    )
    for index, result in enumerate(results):
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            continue
        outlines = result.masks.xy if result.masks is not None else None
        detections = [
            Detection(
                int(track),
                *(int(round(value)) for value in xyxy),
                outline=outlines[row] if outlines is not None else None,
            )
            for row, (track, xyxy) in enumerate(
                zip(boxes.id.tolist(), boxes.xyxy.tolist(), strict=True)
            )
        ]
        height, width = result.orig_shape
        # Judged on the whole frame: a masked crop is partly gray by design.
        night = lacks_colour(result.orig_img)
        for detection in detections:
            if not usable(
                detection,
                detections,
                width,
                height,
                min_size=min_size,
                max_covered=max_covered,
            ):
                continue
            name = f"{session}-{video.stem}-{detection.track}"
            path = out / name / f"{index * every:07d}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), cut(result.orig_img, detection, mask_background))
            by_track.setdefault(name, []).append(
                Crop(path, name, session, video.stem, name, night)
            )
    crops = []
    for track_crops in by_track.values():
        if len(track_crops) >= min_crops:
            crops.extend(track_crops)
        else:
            for crop in track_crops:
                crop.path.unlink()
            if track_crops and not any(track_crops[0].path.parent.iterdir()):
                track_crops[0].path.parent.rmdir()
    return crops
