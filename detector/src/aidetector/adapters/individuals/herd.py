"""Recognise tracked individuals against the names people gave their sightings."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError

from aidetector.adapters.individuals.embedding import EmbeddingModel
from aidetector.adapters.individuals.records import NamesFile, SightingRecord
from aidetector.adapters.individuals.scoring import (
    Gallery,
    NamedSighting,
    self_set_threshold,
)
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.images import encode_jpeg
from aidetector.application.ports import IdentificationUnavailable, camera_id
from aidetector.configuration import IndividualsConfig
from aidetector.domain.models import (
    BoundingBox,
    Candidate,
    DetectionEvent,
    Individual,
    Observation,
)

logger = logging.getLogger(__name__)
Image = NDArray[np.uint8]
SIGHTING_CROPS = 4
CANDIDATES = 3
# Smaller pictures carry too little coat for an embedding.
SIDE_MIN = 48
# Kept pictures are shrunk to this longest side; embedding models take less.
SIDE_MAX = 512
EDGE = 2
COVERED = 0.25


@dataclass(frozen=True)
class _Known:
    signature: tuple[int, int] | None
    gallery: Gallery
    threshold: float | None


def _covered(box: BoundingBox, others: Sequence[BoundingBox]) -> bool:
    area = (box.x2 - box.x1) * (box.y2 - box.y1)
    for other in others:
        if other is box:
            continue
        width = min(box.x2, other.x2) - max(box.x1, other.x1)
        height = min(box.y2, other.y2) - max(box.y1, other.y1)
        if width > 0 and height > 0 and width * height > COVERED * area:
            return True
    return False


def _cut(image: Image, box: BoundingBox) -> Image:
    height, width = image.shape[:2]
    crop = image[
        max(0, box.y1) : min(height, box.y2), max(0, box.x1) : min(width, box.x2)
    ]
    scale = SIDE_MAX / max(crop.shape[:2])
    if scale >= 1:
        return np.ascontiguousarray(crop)
    size = (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale)))
    return cv2.resize(crop, size, interpolation=cv2.INTER_AREA)


@dataclass(frozen=True)
class _Seen:
    clear: bool
    area: int
    moment: int
    observation: Observation
    box: BoundingBox


def _spread(ranked: list[_Seen], count: int) -> list[_Seen]:
    """Up to `count` of the best-ranked pictures, at different moments."""
    pool = sorted(ranked[: 2 * count], key=lambda seen: seen.moment)
    picks = np.linspace(0, len(pool) - 1, min(count, len(pool))).round()
    return [pool[int(index)] for index in np.unique(picks)]


def track_crops(
    event: DetectionEvent, labels: frozenset[str], count: int = SIGHTING_CROPS
) -> dict[int, tuple[str, list[Image]]]:
    """Each track's best pictures of the given classes.

    Whole pictures, away from the frame's edge and not largely covered by
    another box, come first, largest first and spread over the event so they
    show different moments; others only make up the number.
    """
    found: dict[int, list[_Seen]] = {}
    labelled: dict[int, str] = {}
    for moment, observation in enumerate(event.observations):
        height, width = observation.image.shape[:2]
        for box in observation.boxes:
            if box.track_id is None or box.label not in labels:
                continue
            if min(box.x2 - box.x1, box.y2 - box.y1) < SIDE_MIN:
                continue
            whole = (
                box.x1 > EDGE
                and box.y1 > EDGE
                and box.x2 < width - EDGE
                and box.y2 < height - EDGE
            )
            found.setdefault(box.track_id, []).append(
                _Seen(
                    whole and not _covered(box, observation.boxes),
                    (box.x2 - box.x1) * (box.y2 - box.y1),
                    moment,
                    observation,
                    box,
                )
            )
            labelled.setdefault(box.track_id, box.label)
    tracks: dict[int, tuple[str, list[Image]]] = {}
    for track_id, seen in found.items():
        ranked = sorted(seen, key=lambda item: item.area, reverse=True)
        chosen = _spread([item for item in ranked if item.clear], count)
        chosen += [item for item in ranked if not item.clear][: count - len(chosen)]
        tracks[track_id] = (
            labelled[track_id],
            [_cut(item.observation.image, item.box) for item in chosen],
        )
    return tracks


class Herd:
    """Named individuals and saved sightings in one folder, shared by every detector.

    Names are read again whenever names.json changes, so people can name
    sightings while monitoring runs. Embeddings are kept per model file; a
    named sighting without one for the current model is embedded again from
    its pictures.
    """

    def __init__(
        self, directory: Path, model: EmbeddingModel, config: IndividualsConfig
    ):
        self.directory = directory
        self.model = model
        self.labels = frozenset(config.labels)
        self.precision = config.precision
        logger.info(
            "Recognising individuals of %s in tracking detectors; model %s",
            ", ".join(sorted(self.labels)),
            model.key,
        )
        self._lock = Lock()
        self._known = _Known(None, Gallery.of(()), None)

    @property
    def sightings(self) -> Path:
        return self.directory / "sightings"

    def _vectors(self, sighting: Path, record: SightingRecord) -> NDArray[np.float32]:
        stored = sighting / f"vectors-{self.model.key}.npy"
        if stored.exists():
            return np.load(stored)
        images = [
            cv2.imread(str(sighting / f"crop-{index}.jpg"))
            for index in range(1, record.crops + 1)
        ]
        if any(image is None for image in images):
            raise IdentificationUnavailable(
                f"Pictures of named sighting {record.id} cannot be read"
            )
        vectors = self.model.embed(images)
        np.save(stored, vectors)
        return vectors

    def _load(self) -> _Known:
        path = self.directory / "names.json"
        try:
            status = path.stat()
        except FileNotFoundError:
            return _Known(None, Gallery.of(()), None)
        signature = (status.st_mtime_ns, status.st_size)
        if signature == self._known.signature:
            return self._known
        names = NamesFile.model_validate_json(path.read_bytes()).names
        named: list[NamedSighting] = []
        for sighting_id, name in names.items():
            sighting = self.sightings / sighting_id
            try:
                record = SightingRecord.model_validate_json(
                    (sighting / "sighting.json").read_bytes()
                )
            except FileNotFoundError:
                logger.warning("Named sighting %s no longer exists", sighting_id)
                continue
            named.append(
                NamedSighting(name, record.seen[:10], self._vectors(sighting, record))
            )
        gallery = Gallery.of(named)
        threshold = self_set_threshold(named, self.precision)
        logger.info(
            "Named individuals: %d from %d sighting(s); naming threshold %s",
            len(gallery.names),
            len(named),
            "not set yet" if threshold is None else f"{threshold:.3f}",
        )
        return _Known(signature, gallery, threshold)

    def known(self) -> tuple[Gallery, float | None]:
        with self._lock:
            try:
                self._known = self._load()
            except OSError as error:
                raise IdentificationUnavailable(
                    f"Cannot read named sightings: {error}"
                ) from error
            except ValidationError as error:
                raise IdentificationUnavailable(
                    "Named sightings are invalid"
                ) from error
            return self._known.gallery, self._known.threshold

    def save(self, record: SightingRecord, images: Sequence[Image], vectors) -> None:
        """Publish a sighting's folder whole, so readers never see it half written."""
        staging = self.sightings / ".pending"
        try:
            staging.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="sighting-", dir=staging
            ) as pending:
                folder = Path(pending)
                for index, image in enumerate(images, start=1):
                    (folder / f"crop-{index}.jpg").write_bytes(encode_jpeg(image, 90))
                np.save(folder / f"vectors-{self.model.key}.npy", vectors)
                (folder / "sighting.json").write_text(
                    record.model_dump_json(), encoding="utf-8"
                )
                folder.rename(self.sightings / record.id)
        except (OSError, MediaError) as error:
            raise IdentificationUnavailable(f"Cannot save sighting: {error}") from error


class TrackIdentifier:
    """One detector's view of the herd; its tracker's IDs mean nothing elsewhere.

    A track is saved as a sighting the first time it appears in an event and
    is compared with the herd in every event it appears in.
    """

    def __init__(self, herd: Herd):
        self.herd = herd
        self._sightings: dict[tuple[str, int], str] = {}

    def identify(self, event: DetectionEvent, event_id: str) -> tuple[Individual, ...]:
        tracks = track_crops(event, self.herd.labels)
        if not tracks:
            return ()
        gallery, threshold = self.herd.known()
        individuals = []
        for track_id, (label, images) in tracks.items():
            vectors = self.herd.model.embed(images)
            key = (event.source, track_id)
            if key not in self._sightings:
                record = SightingRecord(
                    id=uuid4().hex,
                    camera=camera_id(event.source),
                    label=label,
                    track=track_id,
                    seen=event.best.date.isoformat(),
                    event_id=event_id,
                    crops=len(images),
                )
                self.herd.save(record, images, vectors)
                self._sightings[key] = record.id
            candidates: tuple[Candidate, ...] = ()
            recognised = False
            if gallery.names:
                scores = gallery.scores(vectors)
                order = np.argsort(-scores, kind="stable")[:CANDIDATES]
                candidates = tuple(
                    Candidate(gallery.names[i], float(scores[i])) for i in order
                )
                recognised = threshold is not None and candidates[0].score >= threshold
            individuals.append(
                Individual(
                    track_id, label, self._sightings[key], candidates, recognised
                )
            )
        return tuple(individuals)
