"""Read and write the crop manifest every dataset is converted into."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

COLUMNS = ("path", "identity", "session", "camera", "track", "night")
IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})


@dataclass(frozen=True)
class Crop:
    """One picture of one animal.

    `session` orders recordings in time (a day or a video, sortable as text) and is
    what keeps a gallery and its queries apart. `track` groups crops of one
    continuous sighting; empty when unknown. `night` is None when unknown.
    """

    path: Path
    identity: str
    session: str = ""
    camera: str = ""
    track: str = ""
    night: bool | None = None


def _night(value: str) -> bool | None:
    value = value.strip().lower()
    if not value:
        return None
    if value in {"1", "true", "yes", "night"}:
        return True
    if value in {"0", "false", "no", "day"}:
        return False
    raise ValueError(f"night must be 1/0, true/false or day/night, not {value!r}")


def read_manifest(path: Path) -> tuple[Crop, ...]:
    """Read a CSV manifest; picture paths are relative to the manifest's folder."""
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        missing = {"path", "identity"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing column(s) {', '.join(sorted(missing))}")
        crops = []
        for line, row in enumerate(reader, start=2):
            identity = (row.get("identity") or "").strip()
            if not identity or not (row.get("path") or "").strip():
                raise ValueError(f"{path}:{line}: path and identity are required")
            try:
                night = _night(row.get("night") or "")
            except ValueError as error:
                raise ValueError(f"{path}:{line}: {error}") from None
            crops.append(
                Crop(
                    path.parent / row["path"].strip(),
                    identity,
                    (row.get("session") or "").strip(),
                    (row.get("camera") or "").strip(),
                    (row.get("track") or "").strip(),
                    night,
                )
            )
    if not crops:
        raise ValueError(f"{path}: no crops")
    return tuple(crops)


def write_manifest(path: Path, crops: Iterable[Crop]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        for crop in crops:
            writer.writerow(
                (
                    crop.path.relative_to(path.parent).as_posix()
                    if crop.path.is_relative_to(path.parent)
                    else crop.path.as_posix(),
                    crop.identity,
                    crop.session,
                    crop.camera,
                    crop.track,
                    "" if crop.night is None else int(crop.night),
                )
            )


def crops_from_pattern(
    root: Path, pattern: str, night_from_colour: bool = False
) -> tuple[Crop, ...]:
    """Crops whose labels are in their paths, as most public datasets ship them.

    `pattern` is a regular expression matched against each picture's path relative
    to `root`, with a named group `identity` and optionally `session`, `camera`
    and `track`. Pictures it doesn't match are skipped. With `night_from_colour`,
    a picture without colour counts as an infrared night picture.
    """
    expression = re.compile(pattern)
    if "identity" not in expression.groupindex:
        raise ValueError("The pattern needs a named group (?P<identity>...)")
    crops = []
    for picture in sorted(root.rglob("*")):
        if picture.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        match = expression.search(picture.relative_to(root).as_posix())
        if match is None:
            continue
        fields = {
            name: match.group(name) or ""
            for name in ("session", "camera", "track")
            if name in expression.groupindex
        }
        night = is_grayscale(picture) if night_from_colour else None
        crops.append(Crop(picture, match.group("identity"), night=night, **fields))
    if not crops:
        raise ValueError(f"No pictures under {root} match {pattern!r}")
    return tuple(crops)


def is_grayscale(path: Path) -> bool:
    """Infrared night pictures carry no colour: all channels nearly equal."""
    with Image.open(path) as picture:
        if picture.mode in {"L", "LA", "I", "I;16", "1"}:
            return True
        return lacks_colour(np.asarray(picture.convert("RGB")))


def lacks_colour(pixels: np.ndarray, tolerance: float = 4.0) -> bool:
    """True when every pixel's channels are within `tolerance` of each other."""
    sample = pixels[::4, ::4].astype(np.int16)
    return float((sample.max(axis=2) - sample.min(axis=2)).mean()) <= tolerance


def identities(crops: Sequence[Crop]) -> tuple[str, ...]:
    return tuple(sorted({crop.identity for crop in crops}))
