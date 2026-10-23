"""Recognise tracked individuals against the names people gave their sightings."""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError

from aidetector.adapters.individuals.embedding import EmbeddingModel
from aidetector.adapters.individuals.grouping import group
from aidetector.adapters.individuals.records import (
    GroupsFile,
    NamesFile,
    SightingGroup,
    SightingRecord,
    Suggestion,
)
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
# Outside an outline is painted this grey, as in the pictures the models were tested on.
BACKGROUND = 127
# The latest unnamed sightings grouped for naming; grouping takes n² memory.
GROUPED_MAX = 1000
# Older unnamed sightings are removed; named ones are kept.
KEPT_MAX = 2 * GROUPED_MAX
# Seconds of source time: a track is saved as a sighting once it has been seen
# this long with a whole picture, this long with only partial ones, or once it
# has been gone this long; it is forgotten after the last.
SETTLED = 4.0
PARTIAL = 15.0
GONE = 10.0
FORGOTTEN = 600.0
# Seconds between rewrites of groups.json while new sightings keep coming.
REGROUPING = 30.0
# Seconds between looks at names.json for live pictures.
LOOKING = 1.0


@dataclass(frozen=True)
class Known:
    signature: tuple[int, int] | None
    names: dict[str, str]
    gallery: Gallery
    threshold: float | None


_NOTHING_KNOWN = Known(None, {}, Gallery.of(()), None)


def _mean(vectors: NDArray[np.float32]) -> NDArray[np.float32]:
    mean = vectors.mean(axis=0)
    return mean / np.linalg.norm(mean)


def _ranked(
    gallery: Gallery, vectors: NDArray[np.float32], first: str | None = None
) -> list[tuple[str, float]]:
    if not gallery.names:
        return []
    scores = gallery.scores(vectors)
    order = [int(i) for i in np.argsort(-scores, kind="stable")]
    if first in gallery.names:
        given = gallery.names.index(first)
        order = [given, *(i for i in order if i != given)]
    return [(gallery.names[i], float(scores[i])) for i in order[:CANDIDATES]]


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
    """The box's pixels; with an outline, everything outside it is grey, so
    neighbours in the box do not count towards this individual."""
    height, width = image.shape[:2]
    top, left = max(0, box.y1), max(0, box.x1)
    crop = image[top : min(height, box.y2), left : min(width, box.x2)].copy()
    if box.outline:
        inside = np.zeros(crop.shape[:2], np.uint8)
        points = np.asarray(box.outline, np.int32) - (left, top)
        cv2.drawContours(inside, [points], -1, 255, cv2.FILLED)
        crop[inside == 0] = BACKGROUND
    scale = SIDE_MAX / max(crop.shape[:2])
    if scale >= 1:
        return crop
    size = (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale)))
    return cv2.resize(crop, size, interpolation=cv2.INTER_AREA)


@dataclass(frozen=True)
class _Seen:
    area: int
    moment: datetime
    picture: Image


class _Pictures:
    """A track's best pictures so far, cut out as they come, so no frame is kept.

    Whole pictures, away from the frame's edge and not largely covered by
    another box, come first, largest first and spread over time so they show
    different moments; others only make up the number. Outside a box's
    outline, when a segmentation model gave one, pictures are grey.
    """

    def __init__(self, count: int = SIGHTING_CROPS):
        self.count = count
        self._clear: list[_Seen] = []
        self._other: list[_Seen] = []

    def add(self, observation: Observation, box: BoundingBox) -> None:
        width, height = box.x2 - box.x1, box.y2 - box.y1
        if min(width, height) < SIDE_MIN:
            return
        frame_height, frame_width = observation.image.shape[:2]
        clear = (
            box.x1 > EDGE
            and box.y1 > EDGE
            and box.x2 < frame_width - EDGE
            and box.y2 < frame_height - EDGE
            and not _covered(box, observation.boxes)
        )
        kept, room = (
            (self._clear, 2 * self.count) if clear else (self._other, self.count)
        )
        # Only the best `room` can be chosen, so only those are cut out.
        if len(kept) == room and width * height <= kept[-1].area:
            return
        kept.append(
            _Seen(width * height, observation.date, _cut(observation.image, box))
        )
        kept.sort(key=lambda seen: seen.area, reverse=True)
        del kept[room:]

    @property
    def whole(self) -> bool:
        return bool(self._clear)

    def chosen(self) -> list[Image]:
        pool = sorted(self._clear, key=lambda seen: seen.moment)
        picks = np.linspace(0, len(pool) - 1, min(self.count, len(pool))).round()
        chosen = [pool[int(index)] for index in np.unique(picks)]
        chosen += self._other[: self.count - len(chosen)]
        return [seen.picture for seen in chosen]


def _tracked(
    observation: Observation, labels: frozenset[str]
) -> Iterator[tuple[int, str, BoundingBox]]:
    for box in observation.boxes:
        if box.track_id is not None and box.label is not None and box.label in labels:
            yield box.track_id, box.label, box


@dataclass(frozen=True)
class _Sighting:
    id: str
    vectors: NDArray[np.float32]


def _individual(
    track_id: int, label: str, sighting: _Sighting, known: Known
) -> Individual:
    given = known.names.get(sighting.id)
    candidates = tuple(
        Candidate(name, score)
        for name, score in _ranked(known.gallery, sighting.vectors, given)
    )
    # A name a person gave this very sighting outranks any comparison.
    recognised = bool(candidates) and (
        candidates[0].name == given
        or (known.threshold is not None and candidates[0].score >= known.threshold)
    )
    return Individual(track_id, label, sighting.id, candidates, recognised)


class Herd:
    """Named individuals and saved sightings in one folder, shared by every detector.

    Names are read again whenever names.json changes, so people can name
    sightings while monitoring runs. Embeddings are kept per model file; a
    named sighting without one for the current model is embedded again from
    its pictures. Sightings are embedded and saved one at a time on the herd's
    own thread, so detection never waits for the model.
    """

    def __init__(
        self, directory: Path, model: EmbeddingModel, config: IndividualsConfig
    ):
        self.directory = directory
        self.model = model
        self.labels = frozenset(config.labels)
        self.precision = config.precision
        logger.info(
            "Recognising individuals of %s in tracking detectors; model %s on %s",
            ", ".join(sorted(self.labels)),
            model.key,
            ", ".join(model.providers),
        )
        self._lock = Lock()
        self._known = _NOTHING_KNOWN
        self._index: dict[str, tuple[str, NDArray[np.float32]]] | None = None
        self._work = ThreadPoolExecutor(1, thread_name_prefix="individuals")
        self._grouping = Lock()
        self._ungrouped = False
        self._regrouped = monotonic()

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

    def _load(self) -> Known:
        path = self.directory / "names.json"
        try:
            status = path.stat()
        except FileNotFoundError:
            return _NOTHING_KNOWN
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
        return Known(signature, names, gallery, threshold)

    def _refresh(self) -> Known:
        try:
            self._known = self._load()
        except OSError as error:
            raise IdentificationUnavailable(
                f"Cannot read named sightings: {error}"
            ) from error
        except ValidationError as error:
            raise IdentificationUnavailable("Named sightings are invalid") from error
        return self._known

    def known(self) -> Known:
        """The named individuals; the same object until names.json changes."""
        with self._lock:
            return self._refresh()

    def _sighting_index(self) -> dict[str, tuple[str, NDArray[np.float32]]]:
        """When each sighting with the current model's embeddings was seen, and
        its mean embedding; read from the folder once, then kept up to date."""
        if self._index is None:
            self._index = {}
            folders = self.sightings.iterdir() if self.sightings.is_dir() else ()
            for folder in folders:
                stored = folder / f"vectors-{self.model.key}.npy"
                if folder.name.startswith(".") or not stored.exists():
                    continue
                record = SightingRecord.model_validate_json(
                    (folder / "sighting.json").read_bytes()
                )
                self._index[record.id] = (record.seen, _mean(np.load(stored)))
        return self._index

    def _remove(self, sighting: str) -> None:
        """Take a sighting's folder away whole, so readers never see it half gone."""
        staging = self.sightings / ".pending"
        staging.mkdir(parents=True, exist_ok=True)
        removed = staging / f"removed-{sighting}"
        (self.sightings / sighting).rename(removed)
        shutil.rmtree(removed)

    def regroup(self) -> None:
        """Write groups.json from the latest unnamed sightings; remove the oldest
        unnamed ones beyond those kept."""
        with self._lock:
            known = self._refresh()
            try:
                index = self._sighting_index()
                unnamed = sorted(
                    (
                        (seen, sighting)
                        for sighting, (seen, _) in index.items()
                        if sighting not in known.names
                    ),
                    reverse=True,
                )
                unnamed, removed = unnamed[:KEPT_MAX], unnamed[KEPT_MAX:]
                for _, sighting in removed:
                    del index[sighting]
                    self._remove(sighting)
                unnamed = unnamed[:GROUPED_MAX]
                groups = []
                if unnamed:
                    vectors = np.stack([index[sighting][1] for _, sighting in unnamed])
                    for members in group(vectors):
                        groups.append(
                            SightingGroup(
                                sightings=[unnamed[i][1] for i in members],
                                suggestions=[
                                    Suggestion(name=name, score=score)
                                    for name, score in _ranked(
                                        known.gallery, vectors[members]
                                    )
                                ],
                            )
                        )
                path = self.directory / "groups.json"
                pending = path.with_suffix(f".{uuid4().hex}.tmp")
                pending.write_text(
                    GroupsFile(model=self.model.key, groups=groups).model_dump_json(),
                    encoding="utf-8",
                )
                pending.replace(path)
            except (OSError, ValidationError) as error:
                raise IdentificationUnavailable(
                    f"Cannot group sightings for naming: {error}"
                ) from error

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
        with self._lock:
            if self._index is not None:
                self._index[record.id] = (record.seen, _mean(vectors))
        with self._grouping:
            self._ungrouped = True

    def submit[T](self, job: Callable[[], T]) -> Future[T]:
        """Run work on the herd's thread, after the work submitted before it."""
        return self._work.submit(job)

    def _regroup_in_background(self) -> None:
        try:
            self.regroup()
        except IdentificationUnavailable as error:
            logger.error("Grouping sightings for naming failed: %s", error)

    def regroup_soon(self) -> None:
        """Group new sightings on the herd's thread, at most every REGROUPING
        seconds; cheap enough to call for every observation."""
        with self._grouping:
            if not self._ungrouped or monotonic() - self._regrouped < REGROUPING:
                return
            self._ungrouped = False
            self._regrouped = monotonic()
        self._work.submit(self._regroup_in_background)

    def flush(self) -> None:
        """Wait for the sightings being saved, then group any new ones."""
        self._work.submit(lambda: None).result()
        with self._grouping:
            ungrouped, self._ungrouped = self._ungrouped, False
            self._regrouped = monotonic()
        if ungrouped:
            self.regroup()

    def close(self) -> None:
        try:
            self.flush()
        except IdentificationUnavailable as error:
            logger.error("Grouping sightings for naming failed: %s", error)
        finally:
            self._work.shutdown()


class _Track:
    """A track's pictures until its sighting is submitted, then the sighting."""

    def __init__(self, label: str, seen: datetime):
        self.label = label
        self.first = seen
        self.last = seen
        self.pictures = _Pictures()
        self.sighting: Future[_Sighting | None] | None = None
        # The comparison shown live, with the names it was made against.
        self.shown: tuple[Known, Individual] | None = None


class TrackIdentifier:
    """One detector's view of the herd; its tracker's IDs mean nothing elsewhere.

    Every track of the configured classes is watched as detection goes. Once
    it has been seen for a few seconds, or has gone, its best pictures are
    saved as a sighting on the herd's thread. Live pictures and
    events then compare that sighting with the named individuals; an event
    saves its tracks that are not saved yet, and waits for them.
    """

    def __init__(self, herd: Herd):
        self.herd = herd
        self._tracks: dict[str, dict[int, _Track]] = {}
        self._lock = Lock()
        self._known = _NOTHING_KNOWN
        self._looked = -LOOKING
        self._failure: str | None = None

    def _save(
        self, source: str, track_id: int, track: _Track, event_id: str | None = None
    ) -> Future[_Sighting | None]:
        pictures = track.pictures.chosen()
        track.pictures = _Pictures()

        def save() -> _Sighting | None:
            if not pictures:
                return None
            vectors = self.herd.model.embed(pictures)
            record = SightingRecord(
                id=uuid4().hex,
                camera=camera_id(source),
                label=track.label,
                track=track_id,
                seen=track.first.isoformat(),
                event_id=event_id,
                crops=len(pictures),
            )
            self.herd.save(record, pictures, vectors)
            return _Sighting(record.id, vectors)

        track.sighting = self.herd.submit(save)
        track.sighting.add_done_callback(_report_failure)
        return track.sighting

    def observe(self, source: str, observation: Observation) -> None:
        """Watch an observation's tracks; cheap enough to call for every one."""
        now = observation.date
        with self._lock:
            tracks = self._tracks.setdefault(source, {})
            for track_id, label, box in _tracked(observation, self.herd.labels):
                track = tracks.get(track_id)
                if track is None:
                    track = tracks[track_id] = _Track(label, now)
                track.last = now
                if track.sighting is None:
                    track.pictures.add(observation, box)
                    seen = (now - track.first).total_seconds()
                    # One coming in from the edge waits for a whole picture.
                    if seen >= SETTLED and (track.pictures.whole or seen >= PARTIAL):
                        self._save(source, track_id, track)
            for track_id, track in list(tracks.items()):
                away = (now - track.last).total_seconds()
                if away >= FORGOTTEN:
                    del tracks[track_id]
                elif away >= GONE and track.sighting is None:
                    self._save(source, track_id, track)
        self.herd.regroup_soon()

    def _latest_known(self) -> Known:
        if monotonic() - self._looked >= LOOKING:
            self._looked = monotonic()
            try:
                self._known = self.herd.known()
                self._failure = None
            except IdentificationUnavailable as error:
                if str(error) != self._failure:
                    logger.warning("Live names unavailable: %s", error)
                    self._failure = str(error)
        return self._known

    def identity(self, source: str, track_id: int) -> Individual | None:
        """What the live pictures show for a track; None until it is saved.

        Meant for one live-picture thread: names.json is looked at once a
        second, and a track is compared again only after it changed.
        """
        with self._lock:
            track = self._tracks.get(source, {}).get(track_id)
        if (
            track is None
            or track.sighting is None
            or not track.sighting.done()
            or track.sighting.exception() is not None
        ):
            return None
        sighting = track.sighting.result()
        if sighting is None:
            return None
        known = self._latest_known()
        if track.shown is None or track.shown[0] is not known:
            track.shown = (known, _individual(track_id, track.label, sighting, known))
        return track.shown[1]

    def _event_tracks(self, event: DetectionEvent) -> dict[int, _Track]:
        """The event's tracks, in the order they appear. Those live pictures
        never showed, such as ones seen only between them, come from the event."""
        with self._lock:
            watched = set(self._tracks.get(event.source, {}))
        order: dict[int, None] = {}
        fresh: dict[int, _Track] = {}
        for observation in event.observations:
            for track_id, label, box in _tracked(observation, self.herd.labels):
                order[track_id] = None
                if track_id not in watched:
                    track = fresh.setdefault(track_id, _Track(label, observation.date))
                    track.last = observation.date
                    track.pictures.add(observation, box)
        with self._lock:
            tracks = self._tracks.setdefault(event.source, {})
            for track_id, track in fresh.items():
                tracks.setdefault(track_id, track)
            return {track_id: tracks[track_id] for track_id in order}

    def identify(self, event: DetectionEvent, event_id: str) -> tuple[Individual, ...]:
        started = perf_counter()
        tracks = self._event_tracks(event)
        with self._lock:
            pending = [
                (
                    track_id,
                    track.label,
                    track.sighting
                    or self._save(event.source, track_id, track, event_id),
                )
                for track_id, track in tracks.items()
            ]
        saved = [
            (track_id, label, sighting)
            for track_id, label, future in pending
            if (sighting := future.result()) is not None
        ]
        if not saved:
            return ()
        known = self.herd.known()
        individuals = tuple(
            _individual(track_id, label, sighting, known)
            for track_id, label, sighting in saved
        )
        logger.info(
            "Compared %d track(s) with the named individuals in %.0fms",
            len(individuals),
            (perf_counter() - started) * 1000,
        )
        return individuals


def _report_failure(future: Future) -> None:
    error = future.exception()
    if isinstance(error, IdentificationUnavailable):
        logger.error("Saving a sighting failed: %s", error)
    elif error is not None:
        logger.error("Saving a sighting failed", exc_info=error)
