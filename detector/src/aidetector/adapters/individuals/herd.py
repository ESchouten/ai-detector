"""Recognise tracked individuals against the names people gave their sightings."""

from __future__ import annotations

import logging
import shutil
import tempfile
from bisect import bisect_left
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import Event, Lock
from time import monotonic, perf_counter
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError

from aidetector.adapters.individuals.coat import CoatModel, Described
from aidetector.adapters.individuals.embedding import EmbeddingModel
from aidetector.adapters.individuals.grouping import group
from aidetector.adapters.individuals.records import (
    CoatRecord,
    GroupsFile,
    NamesFile,
    SightingGroup,
    SightingRecord,
    Suggestion,
    TagCrop,
    TagRecord,
)
from aidetector.adapters.individuals.scoring import (
    Decision,
    Gallery,
    NamedSighting,
    Picture,
    decide_together,
    self_set_threshold,
    with_coat,
)
from aidetector.adapters.individuals.tags import TAG_MARGIN, Tag, TagReader, around
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
Outline = tuple[tuple[int, int], ...]
# A box as fractions of its picture's width and height, so that detectors
# that analyse the same camera at different sizes can compare theirs.
Place = tuple[float, float, float, float]
SIGHTING_CROPS = 4
CANDIDATES = 3
# Smaller pictures carry too little coat for an embedding.
SIDE_MIN = 48
# Kept pictures are shrunk to this longest side; embedding models take less.
SIDE_MAX = 512
EDGE = 2
COVERED = 0.25
# Outside an outline is painted this grey for the model, as in the pictures the
# models were tested on; people see the pictures whole, with the outline drawn.
BACKGROUND = 127
# Pixels a saved outline may stray from the segmentation's.
OUTLINE_TOLERANCE = 1.0
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
# Where a track was is kept every PLACED seconds, PLACES_MAX times at most, for
# the events of detectors that do not follow individuals themselves. A track is
# in such an event when at least INSIDE of its box is inside the event's boxes
# on half or more of the event's pictures with boxes that it was there for,
# going by where it was within NEARBY seconds of each, and on OFTEN of them at
# least, or on half of them all in a shorter event. So a track that was only
# there for a part of a long event counts too: the tracker may follow the same
# individual under a new number halfway.
PLACED = 0.5
PLACES_MAX = 1200
INSIDE = 0.5
NEARBY = 1.0
OFTEN = 3
# After its sighting is saved, a track goes on showing the individual from
# other sides. One picture is embedded every LATER seconds of source time, as
# long as fewer than WAITING_MAX wait for the model, and LATER_MAX at most are
# kept, thinned so they stay spread over the track's life. They are written to
# its sighting every KEEPING seconds. Once the sighting has a name they are
# compared against like its pictures; nothing is asked with them.
LATER = 2.0
LATER_MAX = 128
WAITING_MAX = 4
KEEPING = 30.0
# Sightings whose keypoints are remembered for the coat check, a few hundred
# kilobytes a picture.
DESCRIBED_MAX = 64
# Seconds between rewrites of groups.json while new sightings keep coming.
REGROUPING = 30.0
# Seconds between looks at names.json for live pictures.
LOOKING = 1.0
# With a tag reader, a saved track's picture is searched for tags every
# TAG_LOOK seconds of source time, when the reader has time. A number is
# suggested once the reader was TAG_SURE of it on TAG_AGREEING tag pictures,
# and the TAG_CROPS tallest tags are kept as pictures.
TAG_LOOK = 2.0
TAG_SURE = 0.9
TAG_AGREEING = 2
TAG_CROPS = 16


@dataclass(frozen=True)
class Known:
    signature: tuple[int, int, int] | None
    names: dict[str, str]
    gallery: Gallery
    threshold: float | None
    # With a coat check: the threshold for scores with shared coat details
    # added, once it is set for these names or for the names before them.
    coat_threshold: float | None = None


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


def _cut(image: Image, box: BoundingBox) -> tuple[Image, Outline]:
    """The box's pixels, and the outline within them when a segmentation model
    gave one."""
    height, width = image.shape[:2]
    top, left = max(0, box.y1), max(0, box.x1)
    crop = image[top : min(height, box.y2), left : min(width, box.x2)].copy()
    scale = min(1.0, SIDE_MAX / max(crop.shape[:2]))
    if scale < 1:
        size = (
            max(1, round(crop.shape[1] * scale)),
            max(1, round(crop.shape[0] * scale)),
        )
        crop = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
    if not box.outline:
        return crop, ()
    points = np.rint((np.asarray(box.outline) - (left, top)) * scale).astype(np.int32)
    simple = cv2.approxPolyDP(points, OUTLINE_TOLERANCE, closed=True).reshape(-1, 2)
    return crop, tuple((int(x), int(y)) for x, y in simple)


def _masked(picture: Image, outline: Sequence[Sequence[int]]) -> Image:
    """What the model sees: everything outside the outline grey, so neighbours
    in the box do not count towards this individual."""
    if not outline:
        return picture
    inside = np.zeros(picture.shape[:2], np.uint8)
    cv2.drawContours(inside, [np.asarray(outline, np.int32)], -1, 255, cv2.FILLED)
    masked = picture.copy()
    masked[inside == 0] = BACKGROUND
    return masked


def _model_pictures(folder: Path, record: SightingRecord) -> list[Image]:
    """A saved sighting's pictures as the models see them."""
    images = [
        cv2.imread(str(folder / f"crop-{index}.jpg"))
        for index in range(1, record.crops + 1)
    ]
    if any(image is None for image in images):
        raise IdentificationUnavailable(
            f"Pictures of sighting {record.id} cannot be read"
        )
    outlines = record.outlines or [[]] * record.crops
    return [
        _masked(image, outline) for image, outline in zip(images, outlines, strict=True)
    ]


class CoatCheck:
    """The coat details a saved sighting shares with pictures of named individuals.

    Keypoints are found in the pictures a sighting saved, and remembered for
    the latest DESCRIBED_MAX sightings; any thread may ask. A named sighting's
    counts are kept in its folder, so only new pairs of pictures are compared
    after a restart. Once `stopping` is set, comparisons that have not begun
    are not worth their seconds.
    """

    def __init__(self, model: CoatModel, sightings: Path):
        self.model = model
        self.sightings = sightings
        self.stopping = Event()
        self._described: OrderedDict[str, list[Described]] = OrderedDict()
        self._describing = Lock()

    def _details(self, sighting: str) -> list[Described]:
        with self._describing:
            if sighting in self._described:
                self._described.move_to_end(sighting)
                return self._described[sighting]
            folder = self.sightings / sighting
            try:
                record = SightingRecord.model_validate_json(
                    (folder / "sighting.json").read_bytes()
                )
            except OSError as error:
                raise IdentificationUnavailable(
                    f"Cannot read sighting {sighting}: {error}"
                ) from error
            except ValidationError as error:
                raise IdentificationUnavailable(
                    f"Sighting {sighting} is invalid"
                ) from error
            described = [
                self.model.describe(picture)
                for picture in _model_pictures(folder, record)
            ]
            self._described[sighting] = described
            if len(self._described) > DESCRIBED_MAX:
                self._described.popitem(last=False)
            return described

    def similarities(
        self,
        sighting: str,
        vectors: NDArray[np.float32],
        gallery: Gallery,
        shared: dict[Picture, int],
    ) -> NDArray[np.float32]:
        """A saved sighting's similarity to each name, with the coat details it
        shares with the names it resembles most: per name, those of the best
        pair of pictures. `shared` remembers the sighting's count for every
        picture it was compared with."""
        similarities = gallery.similarities(vectors)
        counts = {}
        for owner, pictures in gallery.shortlist(vectors, similarities).items():
            for picture in pictures:
                if picture not in shared:
                    other = self._details(picture[0])[picture[1]]
                    shared[picture] = max(
                        self.model.shared(own, other) for own in self._details(sighting)
                    )
            counts[owner] = max(shared[picture] for picture in pictures)
        return with_coat(similarities, counts)

    def kept(self, sighting: str) -> dict[Picture, int]:
        """The counts kept for a sighting; none before it was first compared."""
        stored = self.sightings / sighting / f"coat-{self.model.key}.json"
        try:
            record = CoatRecord.model_validate_json(stored.read_bytes())
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise IdentificationUnavailable(
                f"Cannot read the coat details of sighting {sighting}: {error}"
            ) from error
        except ValidationError as error:
            raise IdentificationUnavailable(
                f"The coat details of sighting {sighting} are invalid"
            ) from error
        return {
            (other, place): count
            for other, places in record.shared.items()
            for place, count in places.items()
        }

    def keep(self, sighting: str, shared: Mapping[Picture, int]) -> None:
        """Replace the counts kept for a sighting; one removed meanwhile keeps
        nothing."""
        record = CoatRecord(shared={})
        for (other, place), count in shared.items():
            record.shared.setdefault(other, {})[place] = count
        stored = self.sightings / sighting / f"coat-{self.model.key}.json"
        pending = stored.with_suffix(f".{uuid4().hex}.tmp")
        try:
            pending.write_text(record.model_dump_json(), encoding="utf-8")
            pending.replace(stored)
        except FileNotFoundError:
            return
        except OSError as error:
            pending.unlink(missing_ok=True)
            raise IdentificationUnavailable(
                f"Cannot save a sighting's coat details: {error}"
            ) from error


class _Stopping(Exception):
    """The herd is closing while the coat check's threshold is being set."""


@dataclass(frozen=True)
class _Seen:
    area: int
    moment: datetime
    picture: Image
    outline: Outline


class _Pictures:
    """A track's best pictures so far, cut out as they come, so no frame is kept.

    Whole pictures, away from the frame's edge and not largely covered by
    another box, come first, largest first and spread over time so they show
    different moments; others only make up the number. Each keeps its
    outline, when a segmentation model gave one.
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
            _Seen(width * height, observation.date, *_cut(observation.image, box))
        )
        kept.sort(key=lambda seen: seen.area, reverse=True)
        del kept[room:]

    @property
    def whole(self) -> bool:
        return bool(self._clear)

    def chosen(self) -> list[_Seen]:
        pool = sorted(self._clear, key=lambda seen: seen.moment)
        picks = np.linspace(0, len(pool) - 1, min(self.count, len(pool))).round()
        chosen = [pool[int(index)] for index in np.unique(picks)]
        return chosen + self._other[: self.count - len(chosen)]


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


class _Later:
    """Embeddings of a track's pictures after its sighting, spread over its life.

    Filled on the herd's thread; `spacing` and `unkept` are also read while
    observing.
    """

    def __init__(self) -> None:
        self.vectors: list[NDArray[np.float32]] = []
        self.spacing = LATER
        self.unkept = False

    def add(
        self,
        vector: NDArray[np.float32],
        sighting: _Sighting,
        beside: Sequence[NDArray[np.float32]],
    ) -> None:
        """Keep a picture, unless it looks more like a sighting seen beside this
        track: a tracker's number can jump to a neighbour, whose pictures must
        not count for this one. Her own other sides do count, however little
        they look like her first pictures."""
        known = np.concatenate(
            [sighting.vectors, *(kept[None] for kept in self.vectors)]
        )
        own = float((known @ vector).max())
        if any(float((other @ vector).max()) > own for other in beside):
            return
        self.vectors.append(vector)
        self.unkept = True
        if len(self.vectors) > LATER_MAX:
            del self.vectors[1::2]
            self.spacing *= 2


@dataclass(frozen=True)
class _Read:
    """A tag whose number the reader was sure of, in the picture it was on."""

    tag: Tag
    picture: Image
    times: int = 1


class _Tags:
    """What the tags on a track's pictures showed. Filled on the tag
    reader's thread; `number` is also read for live pictures."""

    def __init__(self) -> None:
        self.crops: list[Tag] = []
        self.sure: dict[str, _Read] = {}
        self.number: str | None = None
        self.kept: datetime | None = None
        self.unkept = False

    def add(self, tags: Sequence[Tag], picture: Image, digits: int) -> None:
        """Count the numbers the reader is sure of, each with its surest tag,
        and keep the tallest tags."""
        for tag in tags:
            # A digit too many is the small check digit printed after a number,
            # which the reader need not be sure of.
            text, sure = tag.text, tag.sure
            if len(text) == digits + 1:
                text, sure = text[:digits], sure[:digits]
            if (
                min(sure, default=0.0) < TAG_SURE
                or len(text) != digits
                or not (text.isascii() and text.isdigit())
            ):
                continue
            read = self.sure.get(text)
            if read is None:
                self.sure[text] = _Read(tag, picture)
            elif tag.confidence > read.tag.confidence:
                self.sure[text] = _Read(tag, picture, read.times + 1)
            else:
                self.sure[text] = replace(read, times=read.times + 1)
        if not tags:
            return
        self.unkept = True
        self.crops = sorted(
            [*self.crops, *tags], key=lambda tag: tag.crop.shape[0], reverse=True
        )[:TAG_CROPS]
        agreed = [
            number for number, read in self.sure.items() if read.times >= TAG_AGREEING
        ]
        self.number = max(
            agreed, key=lambda number: self.sure[number].times, default=None
        )

    def record(self) -> tuple[TagRecord, dict[str, Image]]:
        """What to keep in the sighting's folder: the record and its pictures."""
        pictures = {
            f"tag-{index}.jpg": tag.crop for index, tag in enumerate(self.crops, 1)
        }
        crops = [
            TagCrop(read=tag.text, confidence=round(tag.confidence, 3))
            for tag in self.crops
        ]
        if self.number is None:
            return TagRecord(crops=crops), pictures
        read = self.sure[self.number]
        scale = min(1.0, SIDE_MAX / max(read.picture.shape[:2]))
        picture = read.picture
        if scale < 1:
            size = (
                max(1, round(picture.shape[1] * scale)),
                max(1, round(picture.shape[0] * scale)),
            )
            picture = cv2.resize(picture, size, interpolation=cv2.INTER_AREA)
        pictures |= {"tag-picture.jpg": picture, "tag-read.jpg": read.tag.crop}
        x1, y1, x2, y2 = (round(value * scale) for value in read.tag.box)
        return TagRecord(
            number=self.number, box=(x1, y1, x2, y2), crops=crops
        ), pictures


def _worn(tag: Tag, outline: NDArray[np.int32]) -> bool:
    """Whether a tag hangs on the individual with this outline: its middle is
    within the outline or no further from it than half the tag's height, since
    a segmentation model may leave the tag itself out."""
    x1, y1, x2, y2 = tag.box
    centre = ((x1 + x2) / 2, (y1 + y2) / 2)
    return cv2.pointPolygonTest(outline, centre, measureDist=True) >= (y1 - y2) / 2


def _individual(
    track_id: int,
    label: str,
    sighting: _Sighting,
    names: Sequence[str],
    decision: Decision,
    given: int | None,
) -> Individual:
    order = [
        int(i)
        for i in np.argsort(-decision.scores, kind="stable")
        if np.isfinite(decision.scores[i])
    ]
    # A name a person gave this very sighting outranks any comparison.
    if given is not None:
        order = [given, *(i for i in order if i != given)]
    candidates = tuple(
        Candidate(names[i], float(decision.scores[i])) for i in order[:CANDIDATES]
    )
    return Individual(track_id, label, sighting.id, candidates, decision.recognised)


class _Spare:
    """Work for one thread that can be skipped: no more is taken while
    WAITING_MAX jobs wait for it."""

    def __init__(self, work: ThreadPoolExecutor, report: Callable[[Future], None]):
        self._work = work
        self._report = report
        self._waiting = 0
        self._counting = Lock()

    @property
    def free(self) -> bool:
        return self._waiting < WAITING_MAX

    def submit(self, job: Callable[[], None]) -> None:
        def run() -> None:
            try:
                job()
            finally:
                with self._counting:
                    self._waiting -= 1

        with self._counting:
            self._waiting += 1
        self._work.submit(run).add_done_callback(self._report)


class Herd:
    """Named individuals and saved sightings in one folder, shared by every detector.

    Names are read again whenever names.json changes, so people can name
    sightings while monitoring runs. Embeddings are kept per model file; a
    named sighting without one for the current model is embedded again from
    its pictures. Sightings are embedded and saved one at a time on the herd's
    own thread, so detection never waits for the model. With a coat check, a
    second thread sets the threshold for its scores and compares the coats of
    tracks on live pictures. With a tag reader, a third reads the tags on
    tracks' pictures.
    """

    def __init__(
        self,
        directory: Path,
        model: EmbeddingModel,
        config: IndividualsConfig,
        coat: CoatModel | None = None,
        tags: TagReader | None = None,
    ):
        self.directory = directory
        self.model = model
        self.coat = None if coat is None else CoatCheck(coat, self.sightings)
        self.tags = tags
        self.digits = 0 if config.tags is None else config.tags.digits
        self.labels = frozenset(config.labels)
        self.precision = config.precision
        logger.info(
            "Recognising individuals of %s in tracking detectors; model %s on %s",
            ", ".join(sorted(self.labels)),
            model.key,
            ", ".join(model.providers),
        )
        if coat is not None:
            logger.info("Comparing coat details too, on the processor")
        if tags is not None:
            logger.info("Reading the numbers on tags too, on the processor")
        self._lock = Lock()
        self._known = _NOTHING_KNOWN
        self._index: dict[str, tuple[str, NDArray[np.float32]]] | None = None
        self._work = ThreadPoolExecutor(1, thread_name_prefix="individuals")
        # Pictures that can be skipped: a track's later ones, on the herd's
        # thread, and those searched for tags, on their own.
        self.sides = _Spare(self._work, _report_failure)
        self._reading = ThreadPoolExecutor(1, thread_name_prefix="individuals-tags")
        self.tagged = _Spare(self._reading, _report_tag_failure)
        # The later pictures of named sightings.
        self._later: dict[str, NDArray[np.float32]] = {}
        self._richer = 0
        # The coat details each named sighting shares with the others' pictures.
        self._shared: dict[str, dict[Picture, int]] = {}
        self._coats = ThreadPoolExecutor(1, thread_name_prefix="individuals-coat")
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
        vectors = self.model.embed(_model_pictures(sighting, record))
        np.save(stored, vectors)
        return vectors

    def _later_vectors(self, sighting: str) -> NDArray[np.float32] | None:
        """A named sighting's later pictures as embeddings, read once."""
        if sighting not in self._later:
            stored = self.sightings / sighting / f"later-{self.model.key}.npy"
            if not stored.exists():
                return None
            vectors = np.load(stored).astype(np.float32)
            self._later[sighting] = vectors / np.linalg.norm(
                vectors, axis=1, keepdims=True
            )
        return self._later[sighting]

    def _load(self) -> Known:
        path = self.directory / "names.json"
        try:
            status = path.stat()
        except FileNotFoundError:
            return _NOTHING_KNOWN
        signature = (status.st_mtime_ns, status.st_size, self._richer)
        if signature == self._known.signature:
            return self._known
        file = NamesFile.model_validate_json(path.read_bytes())
        names = file.names
        confirmed = set(file.confirmed)
        self._later = {
            sighting: vectors
            for sighting, vectors in self._later.items()
            if sighting in names
        }
        named: list[NamedSighting] = []
        means = {
            sighting: mean for sighting, (_, mean) in self._sighting_index().items()
        }
        for sighting_id, name in names.items():
            sighting = self.sightings / sighting_id
            try:
                record = SightingRecord.model_validate_json(
                    (sighting / "sighting.json").read_bytes()
                )
            except FileNotFoundError:
                logger.warning("Named sighting %s no longer exists", sighting_id)
                continue
            vectors = self._vectors(sighting, record)
            named.append(
                NamedSighting(
                    sighting_id,
                    name,
                    record.seen[:10],
                    vectors,
                    self._later_vectors(sighting_id),
                    sighting_id not in confirmed,
                )
            )
            means[sighting_id] = _mean(vectors)
        # The embedding adapts around every sighting kept, named or not.
        centre = np.mean(list(means.values()), axis=0) if means else None
        gallery = Gallery.of(named, centre)
        threshold = self_set_threshold(named, self.precision)
        logger.info(
            "Named individuals: %d from %d sighting(s) and %d later picture(s); "
            "naming threshold %s",
            len(gallery.names),
            len(named),
            sum(
                0 if sighting.later is None else len(sighting.later)
                for sighting in named
            ),
            "not set yet" if threshold is None else f"{threshold:.3f}",
        )
        known = Known(
            signature,
            names,
            gallery,
            threshold,
            None if threshold is None else self._known.coat_threshold,
        )
        if self.coat is not None:
            self._coats.submit(
                self._set_coat_threshold, self.coat, known, named
            ).add_done_callback(_report_coat_failure)
        return known

    def _set_coat_threshold(
        self, coat: CoatCheck, known: Known, named: Sequence[NamedSighting]
    ) -> None:
        """Set the threshold for scores with the coat check, as the plain one is
        set. Comparing every named sighting's coat takes minutes the first
        time; until then the threshold of the names before stands. The counts
        are kept as they are made, so a restart goes on where this one stopped."""
        with self._lock:
            if self._known is not known:
                # The names changed again; their own threshold follows.
                return
        self._shared = {
            sighting.id: self._shared[sighting.id]
            if sighting.id in self._shared
            else coat.kept(sighting.id)
            for sighting in named
        }

        def compare(sighting: NamedSighting, gallery: Gallery) -> NDArray[np.float32]:
            if coat.stopping.is_set():
                raise _Stopping
            shared = self._shared[sighting.id]
            before = len(shared)
            similarities = coat.similarities(
                sighting.id, sighting.vectors, gallery, shared
            )
            if len(shared) > before:
                coat.keep(sighting.id, shared)
            return similarities

        started = perf_counter()
        try:
            threshold = self_set_threshold(named, self.precision, compare=compare)
        except _Stopping:
            return
        with self._lock:
            self._known = replace(self._known, coat_threshold=threshold)
        logger.info(
            "Naming threshold with the coat check %s, after %.0fs",
            "not set yet" if threshold is None else f"{threshold:.3f}",
            perf_counter() - started,
        )

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

    def keep_later(self, sighting: str, vectors: NDArray[np.float32]) -> None:
        """Replace the embeddings of a sighting's later pictures; a sighting
        removed meanwhile keeps nothing."""
        stored = self.sightings / sighting / f"later-{self.model.key}.npy"
        pending = stored.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with pending.open("wb") as file:
                np.save(file, vectors.astype(np.float16))
            pending.replace(stored)
        except FileNotFoundError:
            return
        except OSError as error:
            pending.unlink(missing_ok=True)
            raise IdentificationUnavailable(
                f"Cannot save a sighting's later pictures: {error}"
            ) from error
        with self._lock:
            if sighting in self._known.names:
                self._later[sighting] = vectors
                self._richer += 1

    def keep_tags(self, sighting: str, tags: _Tags) -> None:
        """Replace what a sighting's tags showed; a sighting removed meanwhile
        keeps nothing."""
        folder = self.sightings / sighting
        record, pictures = tags.record()
        files = {name: encode_jpeg(picture, 90) for name, picture in pictures.items()}
        files["tag.json"] = record.model_dump_json().encode()
        pending = folder / f"tag.{uuid4().hex}.tmp"
        try:
            # The record last, so it never names a picture that is not there.
            for name, content in files.items():
                pending.write_bytes(content)
                pending.replace(folder / name)
        except FileNotFoundError:
            return
        except OSError as error:
            pending.unlink(missing_ok=True)
            raise IdentificationUnavailable(
                f"Cannot save a sighting's tags: {error}"
            ) from error

    def submit[T](self, job: Callable[[], T]) -> Future[T]:
        """Run work on the herd's thread, after the work submitted before it."""
        return self._work.submit(job)

    def submit_coat[T](self, job: Callable[[], T]) -> Future[T]:
        """Compare coats on the second thread, after those submitted before."""
        return self._coats.submit(job)

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
        """Wait for the sightings being saved, the coats being compared and
        the tags being read, then group any new ones."""
        self._work.submit(lambda: None).result()
        self._coats.submit(lambda: None).result()
        self._reading.submit(lambda: None).result()
        with self._grouping:
            ungrouped, self._ungrouped = self._ungrouped, False
            self._regrouped = monotonic()
        if ungrouped:
            self.regroup()

    def close(self) -> None:
        if self.coat is not None:
            self.coat.stopping.set()
        try:
            self.flush()
        except IdentificationUnavailable as error:
            logger.error("Grouping sightings for naming failed: %s", error)
        finally:
            self._work.shutdown()
            self._coats.shutdown()
            self._reading.shutdown()


class _Track:
    """A track's pictures until its sighting is submitted, then the sighting."""

    def __init__(self, label: str, seen: datetime):
        self.label = label
        self.first = seen
        self.last = seen
        self.pictures = _Pictures()
        self.sighting: Future[_Sighting | None] | None = None
        # Where it was and when, oldest first.
        self.places: deque[tuple[datetime, Place]] = deque(maxlen=PLACES_MAX)
        # Pictures after the sighting, when the last was taken and last kept.
        self.later = _Later()
        self.asked = seen
        self.kept = seen
        # The tags on its pictures, and when they were last looked for.
        self.tags = _Tags()
        self.looked = seen
        # Tracks seen in the same picture: other individuals.
        self.beside: set[int] = set()
        # The sighting's similarity to each named individual, with the names it
        # was compared against.
        self.compared: tuple[Known, NDArray[np.float32]] | None = None
        # The same with the coat check, by one thread at a time: the names
        # live pictures last asked it for, its last answer, and the coat
        # details the sighting shares with every picture it was compared with.
        self.check: Known | None = None
        self.checking = Lock()
        self.checked: tuple[Known, NDArray[np.float32]] | None = None
        self.shared: dict[Picture, int] = {}

    def similarities(self, known: Known, sighting: _Sighting) -> NDArray[np.float32]:
        if self.compared is None or self.compared[0] is not known:
            self.compared = (known, known.gallery.similarities(sighting.vectors))
        return self.compared[1]

    @property
    def saved(self) -> _Sighting | None:
        if (
            self.sighting is None
            or not self.sighting.done()
            or self.sighting.exception() is not None
        ):
            return None
        return self.sighting.result()


def _decide(
    saved: dict[int, tuple[_Track, _Sighting]],
    known: Known,
    similarities: Callable[[_Track, _Sighting], NDArray[np.float32]],
    threshold: float | None,
) -> dict[int, Individual]:
    names = known.gallery.names
    if not names:
        return {
            track_id: Individual(track_id, track.label, sighting.id)
            for track_id, (track, sighting) in saved.items()
        }
    order = list(saved)
    position = {track_id: index for index, track_id in enumerate(order)}
    number = {name: index for index, name in enumerate(names)}
    given = []
    for track_id in order:
        name = known.names.get(saved[track_id][1].id)
        given.append(None if name is None else number.get(name))
    decisions = decide_together(
        [similarities(track, sighting) for track, sighting in saved.values()],
        [
            {position[other] for other in track.beside if other in position}
            for track, _ in saved.values()
        ],
        given,
        threshold,
    )
    return {
        track_id: _individual(track_id, track.label, sighting, names, decision, number)
        for (track_id, (track, sighting)), decision, number in zip(
            saved.items(), decisions, given, strict=True
        )
    }


@dataclass(frozen=True)
class _Naming:
    """A source's saved tracks as last decided together."""

    known: Known
    together: int
    saved: frozenset[int]
    checked: int
    individuals: dict[int, Individual]


def _places(observation: Observation, boxes: Sequence[BoundingBox]) -> list[Place]:
    height, width = observation.image.shape[:2]
    return [
        (box.x1 / width, box.y1 / height, box.x2 / width, box.y2 / height)
        for box in boxes
    ]


def _share(place: Place, box: Place) -> float:
    """How much of a place lies inside a box."""
    width = min(place[2], box[2]) - max(place[0], box[0])
    height = min(place[3], box[3]) - max(place[1], box[1])
    area = (place[2] - place[0]) * (place[3] - place[1])
    return width * height / area if width > 0 and height > 0 and area > 0 else 0.0


def _place_at(places: Sequence[tuple[datetime, Place]], date: datetime) -> Place | None:
    """Where a track was nearest to a moment, if it was seen about then."""
    index = bisect_left(places, date, key=lambda place: place[0])
    near = min(
        places[max(index - 1, 0) : index + 1],
        key=lambda place: abs((place[0] - date).total_seconds()),
        default=None,
    )
    if near is None or abs((near[0] - date).total_seconds()) > NEARBY:
        return None
    return near[1]


class TrackIdentifier:
    """One detector's view of the herd; its tracker's IDs mean nothing elsewhere.

    Every track of the configured classes is watched as detection goes. Once
    it has been seen for a few seconds, or has gone, its best pictures are
    saved as a sighting on the herd's thread. Live pictures and
    events then compare that sighting with the named individuals; an event
    saves its tracks that are not saved yet, and waits for them. A source's
    saved tracks are decided together, since tracks seen in one picture are
    different individuals. With a coat check, the coat of a track on live
    pictures is compared on the herd's second thread, and the track goes by
    its embedding until that is done; an event compares its own tracks' coats
    before it decides, and waits for no other. An event of a detector that
    follows no individuals itself gets the tracks that were inside its boxes.
    """

    def __init__(self, herd: Herd):
        self.herd = herd
        self._tracks: dict[str, dict[int, _Track]] = {}
        # Per source, how often a track was first seen beside another.
        self._together: dict[str, int] = {}
        self._named: dict[str, _Naming] = {}
        # How many coat checks are done.
        self._checked = 0
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
            vectors = self.herd.model.embed(
                [_masked(seen.picture, seen.outline) for seen in pictures]
            )
            record = SightingRecord(
                id=uuid4().hex,
                camera=camera_id(source),
                label=track.label,
                track=track_id,
                seen=track.first.isoformat(),
                event_id=event_id,
                crops=len(pictures),
                outlines=[list(seen.outline) for seen in pictures],
            )
            self.herd.save(record, [seen.picture for seen in pictures], vectors)
            return _Sighting(record.id, vectors)

        track.sighting = self.herd.submit(save)
        track.sighting.add_done_callback(_report_failure)
        track.asked = track.kept = track.last
        return track.sighting

    def _look_later(
        self,
        tracks: dict[int, _Track],
        track: _Track,
        observation: Observation,
        box: BoundingBox,
    ) -> None:
        """Embed one more picture of a saved track, when the model has time."""
        if min(box.x2 - box.x1, box.y2 - box.y1) < SIDE_MIN or not self.herd.sides.free:
            return
        track.asked = observation.date
        picture, outline = _cut(observation.image, box)
        others = [tracks[other] for other in track.beside if other in tracks]

        def embed() -> None:
            if (sighting := track.saved) is None:
                return
            vector = self.herd.model.embed([_masked(picture, outline)])[0]
            beside = [
                saved.vectors for other in others if (saved := other.saved) is not None
            ]
            track.later.add(vector, sighting, beside)

        self.herd.sides.submit(embed)

    def _look_for_tags(
        self,
        reader: TagReader,
        track: _Track,
        observation: Observation,
        box: BoundingBox,
    ) -> None:
        """Read the tags on one more picture of a saved track, at the size the
        camera gave it and with a margin, since ears stick out of a box, when
        the reader has time."""
        if (
            min(box.x2 - box.x1, box.y2 - box.y1) < SIDE_MIN
            or not self.herd.tagged.free
        ):
            return
        moment = track.looked = observation.date
        left, top, right, bottom = around(
            observation.image, (box.x1, box.y1, box.x2, box.y2), TAG_MARGIN
        )
        picture = observation.image[top:bottom, left:right].copy()
        outline = np.asarray(box.outline, np.int32).reshape(-1, 2) - (left, top)
        tags = track.tags

        def read() -> None:
            if (sighting := track.saved) is None:
                return
            number = tags.number
            tags.add(
                [
                    tag
                    for tag in reader.read(picture)
                    if not len(outline) or _worn(tag, outline)
                ],
                picture,
                self.herd.digits,
            )
            # A new suggestion at once; the pictures every KEEPING seconds.
            if tags.unkept and (
                tags.number != number
                or tags.kept is None
                or (moment - tags.kept).total_seconds() >= KEEPING
            ):
                tags.unkept = False
                tags.kept = moment
                self.herd.keep_tags(sighting.id, tags)

        self.herd.tagged.submit(read)

    def _look_again(
        self,
        tracks: dict[int, _Track],
        track: _Track,
        observation: Observation,
        box: BoundingBox,
    ) -> None:
        """Look at a saved track when it is time: at another side of it, and
        at its tags."""
        now = observation.date
        if (now - track.asked).total_seconds() >= track.later.spacing:
            self._look_later(tracks, track, observation, box)
        reader = self.herd.tags
        if reader is not None and (now - track.looked).total_seconds() >= TAG_LOOK:
            self._look_for_tags(reader, track, observation, box)

    def _keep_later(self, track: _Track) -> None:
        def keep() -> None:
            if (sighting := track.saved) is not None and track.later.unkept:
                track.later.unkept = False
                self.herd.keep_later(sighting.id, np.stack(track.later.vectors))

        self.herd.submit(keep).add_done_callback(_report_failure)

    def _seen_together(
        self, source: str, tracks: dict[int, _Track], seen: set[int]
    ) -> None:
        for track_id in seen:
            beside = seen - {track_id}
            if not beside <= tracks[track_id].beside:
                tracks[track_id].beside |= beside
                self._together[source] = self._together.get(source, 0) + 1

    def observe(self, source: str, observation: Observation) -> None:
        """Watch an observation's tracks; cheap enough to call for every one."""
        now = observation.date
        with self._lock:
            tracks = self._tracks.setdefault(source, {})
            seen = set()
            for track_id, label, box in _tracked(observation, self.herd.labels):
                seen.add(track_id)
                track = tracks.get(track_id)
                if track is None:
                    track = tracks[track_id] = _Track(label, now)
                track.last = now
                if (
                    not track.places
                    or (now - track.places[-1][0]).total_seconds() >= PLACED
                ):
                    track.places.append((now, _places(observation, [box])[0]))
                if track.sighting is None:
                    track.pictures.add(observation, box)
                    since = (now - track.first).total_seconds()
                    # One coming in from the edge waits for a whole picture.
                    if since >= SETTLED and (track.pictures.whole or since >= PARTIAL):
                        self._save(source, track_id, track)
                else:
                    self._look_again(tracks, track, observation, box)
            self._seen_together(source, tracks, seen)
            for track_id, track in list(tracks.items()):
                away = (now - track.last).total_seconds()
                if away >= FORGOTTEN:
                    del tracks[track_id]
                elif away >= GONE and track.sighting is None:
                    self._save(source, track_id, track)
                elif (
                    track.later.unkept and (now - track.kept).total_seconds() >= KEEPING
                ):
                    track.kept = now
                    self._keep_later(track)
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

    def _check(
        self, coat: CoatCheck, track: _Track, known: Known, sighting: _Sighting
    ) -> None:
        """Compare a track's coat with the names it resembles most, once for
        the same names."""
        with track.checking:
            if track.checked is not None and track.checked[0] is known:
                return
            track.checked = (
                known,
                coat.similarities(
                    sighting.id, sighting.vectors, known.gallery, track.shared
                ),
            )
        with self._lock:
            self._checked += 1

    def _check_soon(self, track: _Track, known: Known, sighting: _Sighting) -> None:
        """Have the coat of a track on live pictures compared, unless that was
        asked for these names before."""
        coat = self.herd.coat
        if coat is None or known.coat_threshold is None or track.check is known:
            return
        track.check = known

        def check() -> None:
            # Not worth its seconds once the names changed or the herd closes.
            if track.check is known and not coat.stopping.is_set():
                self._check(coat, track, known, sighting)

        self.herd.submit_coat(check).add_done_callback(_report_coat_failure)

    def _similarities(
        self, track: _Track, known: Known, sighting: _Sighting
    ) -> NDArray[np.float32]:
        """A track's similarity to each name: with the coat details of its
        last check, when there is a threshold for those and that check asked
        for the same names, and by the embedding otherwise."""
        checked = track.checked
        if (
            known.coat_threshold is not None
            and checked is not None
            and checked[0].gallery.names == known.gallery.names
        ):
            return checked[1]
        return track.similarities(known, sighting)

    def _decided(self, source: str, known: Known) -> dict[int, Individual]:
        """A source's saved tracks, compared with the named individuals and
        decided together; decided again only after something changed."""
        with self._lock:
            tracks = dict(self._tracks.get(source, {}))
            together = self._together.get(source, 0)
            checked = self._checked
        saved = {
            track_id: (track, sighting)
            for track_id, track in tracks.items()
            if (sighting := track.saved) is not None
        }
        naming = self._named.get(source)
        if (
            naming is not None
            and naming.known is known
            and naming.together == together
            and naming.saved == frozenset(saved)
            and naming.checked == checked
        ):
            return naming.individuals
        individuals = _decide(
            saved,
            known,
            lambda track, sighting: self._similarities(track, known, sighting),
            known.threshold if known.coat_threshold is None else known.coat_threshold,
        )
        self._named[source] = _Naming(
            known, together, frozenset(saved), checked, individuals
        )
        return individuals

    def identity(self, source: str, track_id: int) -> Individual | None:
        """What the live pictures show for a track; None until it is saved.

        Meant for one live-picture thread: names.json is looked at once a
        second, and tracks are decided again only after something changed.
        """
        with self._lock:
            track = self._tracks.get(source, {}).get(track_id)
        if track is None or (sighting := track.saved) is None:
            return None
        known = self._latest_known()
        self._check_soon(track, known, sighting)
        individual = self._decided(source, known).get(track_id)
        if individual is None or track.tags.number is None:
            return individual
        return replace(individual, tag=track.tags.number)

    def _event_tracks(self, event: DetectionEvent) -> dict[int, _Track]:
        """The event's tracks, in the order they appear. Those live pictures
        never showed, such as ones seen only between them, come from the event."""
        with self._lock:
            watched = set(self._tracks.get(event.source, {}))
        order: dict[int, None] = {}
        fresh: dict[int, _Track] = {}
        pictures = []
        for observation in event.observations:
            seen = set()
            for track_id, label, box in _tracked(observation, self.herd.labels):
                seen.add(track_id)
                order[track_id] = None
                if track_id not in watched:
                    track = fresh.setdefault(track_id, _Track(label, observation.date))
                    track.last = observation.date
                    track.pictures.add(observation, box)
            pictures.append(seen)
        with self._lock:
            tracks = self._tracks.setdefault(event.source, {})
            for track_id, track in fresh.items():
                tracks.setdefault(track_id, track)
            for seen in pictures:
                self._seen_together(event.source, tracks, seen)
            return {track_id: tracks[track_id] for track_id in order}

    def _inside(self, event: DetectionEvent) -> dict[int, _Track]:
        """The watched tracks that were inside another detector's event, the
        ones most often inside first."""
        with self._lock:
            tracks = dict(self._tracks.get(event.source, {}))
            places = {
                track_id: tuple(track.places) for track_id, track in tracks.items()
            }
        boxed = [observation for observation in event.observations if observation.boxes]
        there = dict.fromkeys(places, 0)
        inside = dict.fromkeys(places, 0)
        for observation in boxed:
            boxes = _places(observation, observation.boxes)
            for track_id, kept in places.items():
                place = _place_at(kept, observation.date)
                if place is None:
                    continue
                there[track_id] += 1
                if max(_share(place, box) for box in boxes) >= INSIDE:
                    inside[track_id] += 1
        often = max(1, min(OFTEN, (len(boxed) + 1) // 2))
        return {
            track_id: tracks[track_id]
            for track_id, pictures in sorted(
                inside.items(), key=lambda counted: counted[1], reverse=True
            )
            if pictures >= often and 2 * pictures >= there[track_id]
        }

    def identify(self, event: DetectionEvent, event_id: str) -> tuple[Individual, ...]:
        return self._identify(event.source, self._event_tracks(event), event_id)

    def identify_inside(
        self, event: DetectionEvent, event_id: str
    ) -> tuple[Individual, ...]:
        """The same for an event of a detector that follows no individuals,
        such as one that finds a mounting: the tracks inside its boxes."""
        return self._identify(event.source, self._inside(event), event_id)

    def _identify(
        self, source: str, tracks: dict[int, _Track], event_id: str
    ) -> tuple[Individual, ...]:
        started = perf_counter()
        with self._lock:
            pending = [
                (
                    track_id,
                    track.sighting or self._save(source, track_id, track, event_id),
                )
                for track_id, track in tracks.items()
            ]
        saved = {
            track_id: sighting
            for track_id, future in pending
            if (sighting := future.result()) is not None
        }
        if not saved:
            return ()
        known = self.herd.known()
        if (coat := self.herd.coat) is not None and known.coat_threshold is not None:
            for track_id, sighting in saved.items():
                self._check(coat, tracks[track_id], known, sighting)
        decided = self._decided(source, known)
        individuals = tuple(decided[track_id] for track_id in saved)
        logger.info(
            "Compared %d track(s) with the named individuals in %.0fms",
            len(individuals),
            (perf_counter() - started) * 1000,
        )
        return individuals


class InsideIdentifier:
    """For a detector that follows no individuals itself, such as one that
    finds a mounting: its events carry the individuals that a detector which
    does follow them saw inside their boxes on the same source."""

    def __init__(self, followers: Mapping[str, TrackIdentifier]):
        self.followers = followers

    def identify(self, event: DetectionEvent, event_id: str) -> tuple[Individual, ...]:
        follower = self.followers.get(event.source)
        return () if follower is None else follower.identify_inside(event, event_id)


def _reporting(what: str) -> Callable[[Future], None]:
    def report(future: Future) -> None:
        error = future.exception()
        if isinstance(error, IdentificationUnavailable):
            logger.error("%s failed: %s", what, error)
        elif error is not None:
            logger.error("%s failed", what, exc_info=error)

    return report


_report_failure = _reporting("Saving a sighting")
_report_coat_failure = _reporting("Comparing coat details")
_report_tag_failure = _reporting("Reading a tag")
