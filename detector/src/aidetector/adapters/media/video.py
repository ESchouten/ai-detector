"""Prepare event frames and encode bounded MP4 attachments through FFmpeg."""

import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

import cv2
from imageio_ffmpeg import get_ffmpeg_exe

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.images import (
    Image,
    crop_observation,
    draw_boxes,
    even_width,
)
from aidetector.domain.models import BoundingBox, Observation


def _video_frames(
    observations: Sequence[Observation], crop: bool, plot: bool, padding: float
) -> Iterator[Image]:
    boxes = (
        [box for observation in observations for box in observation.boxes]
        if crop
        else []
    )
    region = BoundingBox.enclosing(boxes)
    if region is None:
        for item in observations:
            yield draw_boxes(item) if plot else item.image
        return
    last_box_index = max(index for index, item in enumerate(observations) if item.boxes)
    previous_boxes: Sequence[BoundingBox] = ()
    for index, observation in enumerate(observations):
        previous_boxes = observation.boxes or previous_boxes
        frame = crop_observation(
            observation,
            region=region,
            padding=padding,
            plot=plot,
            plot_boxes=previous_boxes if index <= last_box_index else (),
        )
        yield frame if frame is not None else observation.image


@dataclass(frozen=True)
class _RawVideo:
    path: Path
    width: int
    height: int
    fps: float

    @classmethod
    def from_frames(
        cls, path: Path, frames: Iterator[Image], fps: float
    ) -> "_RawVideo":
        first = next(frames)
        height, width = first.shape[:2]
        # Spool once so every encoding attempt can stream the same input without
        # retaining another full clip of transformed arrays in memory.
        with path.open("wb") as raw:
            for frame in chain((first,), frames):
                if frame.shape[:2] != (height, width):
                    frame = cv2.resize(frame, (width, height))
                raw.write(frame.tobytes())
        return cls(path, width, height, fps)

    def encode(self, executable: str, output: Path, *, width: int, crf: int) -> bytes:
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            "fast",
            "-vf",
            f"scale={width}:-2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output),
        ]
        try:
            with self.path.open("rb") as raw:
                process = subprocess.run(
                    command,
                    stdin=raw,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MediaError("FFmpeg could not finish encoding the event") from error
        if process.returncode:
            diagnostic = process.stderr.decode("utf-8", errors="replace").strip()
            raise MediaError(f"FFmpeg encoding failed: {diagnostic}")
        return output.read_bytes()


def _encoding_attempts(width: int, crf: int) -> Iterator[tuple[int, int]]:
    yield width, crf
    max_crf = max(crf, 36)
    for candidate_crf in range(crf + 4, max_crf + 4, 4):
        yield width, candidate_crf
    while width > 160:
        width = max(160, even_width(int(width * 0.8)))
        yield width, max_crf


def encode_video(
    observations: Sequence[Observation],
    width: int | None = None,
    crf: int = 28,
    crop: bool = True,
    plot: bool = True,
    data_max: int | None = None,
    padding: float = 0.1,
) -> bytes:
    if not observations:
        raise ValueError("A video needs at least one frame")
    try:
        executable = get_ffmpeg_exe()
    except RuntimeError as error:
        raise MediaError(
            "FFmpeg is unavailable; install it or set IMAGEIO_FFMPEG_EXE"
        ) from error
    duration = (observations[-1].date - observations[0].date).total_seconds()
    fps = (len(observations) - 1) / duration if duration > 0 else 1.0
    frames = _video_frames(observations, crop, plot, padding)
    try:
        with tempfile.TemporaryDirectory(prefix="aidetector-media-") as directory:
            raw = _RawVideo.from_frames(Path(directory) / "frames.bgr", frames, fps)
            output = Path(directory) / "video.mp4"
            target_width = even_width(min(width or raw.width, raw.width))
            for candidate_width, candidate_crf in _encoding_attempts(target_width, crf):
                encoded = raw.encode(
                    executable, output, width=candidate_width, crf=candidate_crf
                )
                if data_max is None or len(encoded) <= data_max:
                    return encoded
    except OSError as error:
        raise MediaError("Cannot prepare or read video data") from error
    raise MediaError("MP4 cannot fit the configured size limit")
