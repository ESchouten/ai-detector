"""Cut identified crops out of a video with per-frame boxes, such as ETH's barn set."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from reid.manifest import Crop, is_grayscale


@dataclass(frozen=True)
class Box:
    identity: str
    x1: int
    y1: int
    x2: int
    y2: int


def read_labels(
    directory: Path, frame_pattern: str, width: int, height: int
) -> dict[int, list[Box]]:
    """YOLO-style `id cx cy w h` lines, normalised, one file per frame."""
    expression = re.compile(frame_pattern)
    frames: dict[int, list[Box]] = {}
    for path in directory.iterdir():
        match = expression.search(path.name)
        if match is None:
            continue
        boxes = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            identity, cx, cy, w, h = line.split()[:5]
            x, y, bw, bh = (
                float(cx) * width,
                float(cy) * height,
                float(w) * width,
                float(h) * height,
            )
            boxes.append(
                Box(
                    identity,
                    max(0, round(x - bw / 2)),
                    max(0, round(y - bh / 2)),
                    min(width, round(x + bw / 2)),
                    min(height, round(y + bh / 2)),
                )
            )
        frames[int(match.group(1))] = boxes
    if not frames:
        raise ValueError(f"No label files in {directory} match {frame_pattern!r}")
    return frames


def _usable(box: Box, width: int, height: int, min_size: int, edge: int) -> bool:
    if min(box.x2 - box.x1, box.y2 - box.y1) < min_size:
        return False
    # A cow cut by the picture's edge shows too little of herself to be evidence.
    return (
        box.x1 > edge
        and box.y1 > edge
        and box.x2 < width - edge
        and box.y2 < height - edge
    )


def _frames(video: Path, every: int) -> Iterator[tuple[int, np.ndarray]]:
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot open {video}")
    try:
        index = 0
        while True:
            if not capture.grab():
                return
            if index % every == 0:
                ok, image = capture.retrieve()
                if not ok:
                    return
                yield index, image
            index += 1
    finally:
        capture.release()


def crops_from_labelled_video(
    video: Path,
    labels: Path,
    out: Path,
    *,
    session: str,
    every: int = 30,
    frame_pattern: str = r"(\d+)\.txt$",
    frame_offset: int = 0,
    identity_prefix: str = "",
    min_size: int = 96,
    edge: int = 2,
    track_gap: int = 3,
    night_from_colour: bool = False,
) -> list[Crop]:
    """Save every `every`th frame's usable boxes as crops, grouped into tracks.

    Label file number N belongs to video frame N + `frame_offset`. A track is one
    animal's run of sampled frames, broken after `track_gap` sampled frames
    without her. The first sampled frame is also written with its boxes drawn,
    as `<out>/<video>-preview.jpg`, to check that boxes and frames line up.
    """
    import cv2

    capture = cv2.VideoCapture(str(video))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if not width or not height:
        raise ValueError(f"Cannot read the size of {video}")
    boxes = read_labels(labels, frame_pattern, width, height)
    crops: list[Crop] = []
    last_seen: dict[str, int] = {}
    segment: dict[str, int] = {}
    previewed = False
    for index, image in _frames(video, every):
        frame_boxes = boxes.get(index - frame_offset, [])
        if not previewed and frame_boxes:
            preview = image.copy()
            for box in frame_boxes:
                cv2.rectangle(
                    preview, (box.x1, box.y1), (box.x2, box.y2), (0, 255, 0), 3
                )
                cv2.putText(
                    preview,
                    box.identity,
                    (box.x1, box.y1 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 255, 0),
                    2,
                )
            out.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out / f"{video.stem}-preview.jpg"), preview)
            previewed = True
        sampled = index // every
        for box in frame_boxes:
            if sampled - last_seen.get(box.identity, -(10**9)) > track_gap:
                segment[box.identity] = segment.get(box.identity, -1) + 1
            last_seen[box.identity] = sampled
            if not _usable(box, width, height, min_size, edge):
                continue
            identity = identity_prefix + box.identity
            path = out / identity / f"{session}-{video.stem}-{index:07d}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), image[box.y1 : box.y2, box.x1 : box.x2])
            crops.append(
                Crop(
                    path,
                    identity,
                    session,
                    video.stem,
                    f"{session}-{video.stem}-{box.identity}-{segment[box.identity]}",
                    is_grayscale(path) if night_from_colour else None,
                )
            )
    if not crops:
        raise ValueError(f"No usable boxes in {video}; check --frame-offset and sizes")
    return crops
