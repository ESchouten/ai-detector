"""Recognize individual objects against examples explicitly confirmed in the web app."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass, replace
from datetime import datetime
from threading import Event
from time import monotonic
from typing import cast

import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.identity_gallery import PreparedGallery
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import IdentityConfig
from aidetector.domain.identity import (
    TrackAgreement,
    choose_identity,
    reject_conflicting_matches,
)
from aidetector.domain.models import (
    BoundingBox,
    CaptureStamp,
    IdentityMatch,
    Observation,
)

logger = logging.getLogger(__name__)


def distinct_identity_scores(
    vectors: NDArray[np.float32],
    gallery: NDArray[np.float32],
    owners: tuple[tuple[str, str], ...],
    neighbours: int = 1,
    parts: tuple[int, ...] = (),
    share: float = 0,
) -> list[list[IdentityMatch]]:
    """Compare all confirmed views, then score each cow by its nearest references.

    The nearest are `share` of a cow's references and at least `neighbours`.
    Descriptions that lie side by side in a vector, `parts` wide each, are
    compared one by one: each finds its own nearest references of a cow, and
    the cow's score is their mean.
    """
    similarities = []
    first = 0
    for width in parts or (gallery.shape[1],):
        similarities.append(
            vectors[:, first : first + width] @ gallery[:, first : first + width].T
        )
        first += width
    if not all(np.isfinite(part).all() for part in similarities):
        raise ValueError("Identity embeddings must contain finite values")
    columns: dict[tuple[str, str], list[int]] = {}
    for index, owner in enumerate(owners):
        columns.setdefault(owner, []).append(index)
    results: list[list[IdentityMatch]] = [[] for _ in vectors]
    for (identity_id, name), indices in columns.items():
        count = max(neighbours, round(share * len(indices)))
        nearest = [
            np.sort(part[:, indices], axis=1)[:, -count:].mean(axis=1)
            for part in similarities
        ]
        scores = np.clip(np.mean(nearest, axis=0), -1, 1)
        for matches, score in zip(results, scores, strict=True):
            matches.append(IdentityMatch(identity_id, name, float(score)))
    return results


def infrared(image: NDArray[np.uint8]) -> bool:
    """Whether a camera took this picture under infrared light: it has no colour."""
    sample = image[::8, ::8].astype(np.int16)
    return float(np.abs(sample - sample.mean(axis=2, keepdims=True)).mean()) < 1


def usable_crop(
    box: BoundingBox,
    others: tuple[BoundingBox, ...],
    width: int,
    height: int,
    min_size: int,
    max_overlap: float,
) -> bool:
    """Reject clipped, tiny and overlapping boxes before retaining identity evidence."""
    if box.x1 < 1 or box.y1 < 1 or box.x2 >= width - 1 or box.y2 >= height - 1:
        return False
    w, h = box.x2 - box.x1, box.y2 - box.y1
    if min(w, h) < min_size:
        return False
    area = w * h
    for other in others:
        if other is box:
            continue
        overlap = max(0, min(box.x2, other.x2) - max(box.x1, other.x1)) * max(
            0, min(box.y2, other.y2) - max(box.y1, other.y1)
        )
        other_area = max(1, (other.x2 - other.x1) * (other.y2 - other.y1))
        if overlap / min(area, other_area) > max_overlap:
            return False
    return True


@dataclass
class _SourceState:
    at: datetime
    capture: CaptureStamp | None
    shape: tuple[int, int]


@dataclass
class _Track:
    at: datetime
    candidate: IdentityMatch
    match: IdentityMatch
    saved: datetime | None = None


class GalleryIdentifier:
    """One detector worker owns temporal state; what `prepare` uses may be shared.

    `prepare` turns a confirmed catalog into reference vectors and the encoder
    that describes new crops in their space. It runs on the executor.
    """

    def __init__(
        self,
        settings: IdentityConfig,
        catalog: IdentityCatalog,
        prepare: Callable[[Catalog, Event | None], PreparedGallery],
        executor: Executor,
        *,
        report_status: ReportStatus = ignore_status,
        clock: Callable[[], float] = monotonic,
        preparation_stopped: Event | None = None,
    ):
        self.settings = settings
        self.catalog = catalog
        self.prepare = prepare
        self.executor = executor
        self.clock = clock
        self.report_status = report_status
        self.preparation_stopped = preparation_stopped
        self._retry_at: float | None = None
        self._preparation: tuple[Catalog, Future[PreparedGallery]] | None = None
        self._prepared_catalog: Catalog | None = None
        self.agreement = TrackAgreement(
            settings.min_observations,
            max_gap=max(5, settings.sample_interval * 3),
            hold=settings.hold,
        )
        self._catalog: Catalog | None = None
        self._gallery: PreparedGallery | None = None
        self._tracks: dict[tuple[str, int | None], _Track] = {}
        self._sources: dict[str, _SourceState] = {}

    def _accept_observation(self, source: str, observation: Observation) -> bool:
        previous = self._sources.get(source)
        height, width = observation.image.shape[:2]
        current = _SourceState(observation.date, observation.capture, (height, width))
        if previous is None:
            self._sources[source] = current
            return True
        old_epoch = previous.capture.epoch if previous.capture else None
        epoch = current.capture.epoch if current.capture else None
        elapsed = (current.at - previous.at).total_seconds()
        captured_elapsed = elapsed
        if epoch == old_epoch and current.capture and previous.capture:
            if current.capture.sequence <= previous.capture.sequence:
                return False
            captured_elapsed = (
                current.capture.monotonic_at - previous.capture.monotonic_at
            )
        self._sources[source] = current
        if (
            epoch != old_epoch
            or current.shape != previous.shape
            or min(elapsed, captured_elapsed) < 0
            or max(elapsed, captured_elapsed) > self.agreement.max_gap
        ):
            self._clear_source(source)
        return epoch != old_epoch or (captured_elapsed > 0 and elapsed != 0)

    def _clear_source(self, source: str) -> None:
        self.agreement.clear_source(source)
        self._tracks = {
            key: track for key, track in self._tracks.items() if key[0] != source
        }

    def _refresh_gallery(self) -> Catalog:
        catalog = self.catalog.load()
        if catalog != self._catalog:
            self._catalog = catalog
            self._prepared_catalog = None
            self._gallery = None
            self._tracks.clear()
            self.agreement.clear()
            available = sum(bool(cow.samples) for cow in catalog.identities)
            logger.info(
                "Identity gallery revision %d: %d identities with references, %d photos",
                catalog.revision,
                available,
                sum(len(cow.samples) for cow in catalog.identities),
            )
            self.report_status(
                StatusEvent(
                    "identity_preparing" if available >= 2 else "identity_collecting",
                    message="Preparing identification from the confirmed herd…"
                    if available >= 2
                    else "Collecting photos. Confirm at least two animals to start matching.",
                )
            )
        self._finish_preparation(catalog)
        if (
            self._preparation is None
            and self._prepared_catalog != catalog
            and sum(bool(cow.samples) for cow in catalog.identities) >= 2
        ):
            self._preparation = (
                catalog,
                self.executor.submit(self.prepare, catalog, self.preparation_stopped),
            )
            self._finish_preparation(catalog)
        return catalog

    def _finish_preparation(self, catalog: Catalog) -> None:
        if self._preparation is None or not self._preparation[1].done():
            return
        submitted_catalog, future = self._preparation
        self._preparation = None
        try:
            gallery = future.result()
        except (OSError, sqlite3.Error, ValidationError):
            if submitted_catalog == catalog:
                raise
            logger.debug("Discarded unavailable references from an older herd revision")
            return
        if submitted_catalog != catalog:
            return
        self._prepared_catalog = catalog
        self._gallery = gallery
        self._tracks.clear()
        self.agreement.clear()
        logger.info("Identity gallery revision %d is ready", catalog.revision)
        self.report_status(
            StatusEvent("identity_ready", message="Identification is ready.")
        )

    def _match(
        self, images: list[NDArray[np.uint8]], min_similarity: float
    ) -> list[tuple[IdentityMatch, str | None]]:
        """Per image: the accepted match, and the identity it resembles most."""
        gallery = self._gallery
        if not images:
            return []
        if gallery is None or len(set(gallery.owners)) < 2:
            return [(IdentityMatch(), None) for _ in images]
        vectors = np.concatenate(
            [
                gallery.encoder.encode(images[start : start + 8])
                for start in range(0, len(images), 8)
            ]
        )
        return [
            (
                choose_identity(scores, min_similarity, self.settings.min_margin),
                max(
                    scores, key=lambda score: cast(float, score.similarity)
                ).identity_id,
            )
            for scores in distinct_identity_scores(
                vectors,
                gallery.vectors,
                gallery.owners,
                gallery.neighbours,
                gallery.parts,
                gallery.share,
            )
        ]

    def identify(self, source: str, observation: Observation) -> Observation:
        if self._retry_at is not None and self.clock() < self._retry_at:
            return observation
        if not self._accept_observation(source, observation):
            return replace(
                observation,
                boxes=tuple(
                    replace(box, identity=None)
                    if box.label in self.settings.labels
                    else box
                    for box in observation.boxes
                ),
            )
        try:
            result = self._identify(source, observation)
        except (OSError, sqlite3.Error, ValidationError):
            self._catalog = None
            self._prepared_catalog = None
            self._gallery = None
            self._tracks.clear()
            self.agreement.clear()
            self._retry_at = self.clock() + 60
            logger.exception(
                "Identification unavailable; detection continues. Retrying after 60 seconds"
            )
            self.report_status(
                StatusEvent(
                    "identity_failed",
                    message="Identification is temporarily unavailable. Detection continues; check Logs for details.",
                )
            )
            return observation
        if self._retry_at is not None:
            self._retry_at = None
            logger.info("Identification resumed")
        return result

    def _identify(self, source: str, observation: Observation) -> Observation:
        catalog = self._refresh_gallery()
        self._retire_tracks(source, observation)
        height, width = observation.image.shape[:2]
        eligible = tuple(
            box for box in observation.boxes if box.label in self.settings.labels
        )
        crops: dict[int, NDArray[np.uint8]] = {}
        candidates: dict[int, IdentityMatch] = {}
        matches: dict[int, IdentityMatch] = {}
        for index, box in enumerate(observation.boxes):
            if box.label not in self.settings.labels:
                continue
            matches[index] = IdentityMatch()
            candidates[index] = IdentityMatch()
            if not usable_crop(
                box,
                eligible,
                width,
                height,
                self.settings.min_crop_size,
                self.settings.max_overlap,
            ):
                self._clear_track(
                    source, box.track_id, observation.date, IdentityMatch()
                )
                continue
            track = self._tracks.get((source, box.track_id))
            if (
                track
                and 0
                <= (observation.date - track.at).total_seconds()
                < self.settings.sample_interval
            ):
                candidates[index] = track.candidate
                matches[index] = track.match
                continue
            crops[index] = observation.image[box.y1 : box.y2, box.x1 : box.x2]
        night_limit = self.settings.min_similarity_infrared
        matched = self._match(
            list(crops.values()),
            self.settings.min_similarity
            if night_limit is None or not infrared(observation.image)
            else night_limit,
        )
        candidates.update(zip(crops, (match for match, _ in matched), strict=True))
        claimed = {candidate.identity_id for candidate in candidates.values()}
        # A confirmed animal keeps its name through a weaker crop only while
        # nobody else in view claims that identity.
        resembles = {
            index: likeness if likeness not in claimed else None
            for index, (_, likeness) in zip(crops, matched, strict=True)
        }
        # Pending candidates still compete with visible animals whose sampling
        # clocks differ; waiting for agreement must not hide a known collision.
        for index in self._reject_conflicts(candidates):
            matches[index] = candidates[index]
            self._clear_track(
                source,
                observation.boxes[index].track_id,
                observation.date,
                candidates[index],
            )
        for index, crop in crops.items():
            box = observation.boxes[index]
            matches[index] = self.agreement.update(
                source,
                box.track_id,
                observation.date,
                candidates[index],
                resembles[index],
            )
            self._retain(
                source,
                observation.date,
                box.track_id,
                candidates[index],
                matches[index],
                crop,
                catalog.revision,
            )
        return replace(
            observation,
            boxes=tuple(
                replace(box, identity=matches[i]) if i in matches else box
                for i, box in enumerate(observation.boxes)
            ),
        )

    @staticmethod
    def _reject_conflicts(matches: dict[int, IdentityMatch]) -> set[int]:
        resolved = dict(
            zip(
                matches,
                reject_conflicting_matches(tuple(matches.values())),
                strict=True,
            )
        )
        rejected = {
            index
            for index, match in matches.items()
            if match.identity_id and not resolved[index].identity_id
        }
        matches.update(resolved)
        return rejected

    def _clear_track(
        self, source: str, track_id: int | None, at: datetime, unknown: IdentityMatch
    ) -> None:
        self.agreement.update(source, track_id, at, unknown)
        previous = self._tracks.get((source, track_id))
        if previous is not None:
            previous.candidate = unknown
            previous.match = unknown

    def _retain(
        self,
        source: str,
        at: datetime,
        track_id: int | None,
        candidate: IdentityMatch,
        match: IdentityMatch,
        crop: NDArray[np.uint8],
        gallery_revision: int,
    ) -> None:
        key = (source, track_id)
        previous = self._tracks.get(key)
        saved = previous.saved if previous else None
        if (
            saved is None
            or (at - saved).total_seconds() >= self.settings.review_interval
        ):
            self.catalog.save_sighting(
                crop, source, at, track_id, match, gallery_revision=gallery_revision
            )
            saved = at
        self._tracks[key] = _Track(at, candidate, match, saved)

    def _retire_tracks(self, source: str, observation: Observation) -> None:
        """Forget tracks this source last sampled longer ago than the agreement gap.

        A track the detector misses for a moment is still the tracker's same
        animal, and keeps the agreement it had.
        """
        for key, track in tuple(self._tracks.items()):
            elapsed = (observation.date - track.at).total_seconds()
            if key[0] == source and not 0 <= elapsed <= self.agreement.max_gap:
                self.agreement.update(source, key[1], observation.date, IdentityMatch())
                del self._tracks[key]
