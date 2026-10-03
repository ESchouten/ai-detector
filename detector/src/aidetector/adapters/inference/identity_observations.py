"""Recognize individual objects against examples explicitly confirmed in the web app."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.identity import EmbeddingCache, ImageEncoder
from aidetector.configuration import IdentityConfig
from aidetector.domain.identity import (
    TrackAgreement,
    choose_identity,
    reject_conflicting_matches,
)
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation


def distinct_identity_scores(
    vectors: NDArray[np.float32],
    gallery: NDArray[np.float32],
    owners: tuple[tuple[str, str], ...],
) -> list[list[IdentityMatch]]:
    """Compare all confirmed views, then take each cow's best reference score."""
    similarities = vectors @ gallery.T
    if not np.isfinite(similarities).all():
        raise ValueError("Identity embeddings must contain finite values")
    columns: dict[tuple[str, str], list[int]] = {}
    for index, owner in enumerate(owners):
        columns.setdefault(owner, []).append(index)
    results: list[list[IdentityMatch]] = [[] for _ in vectors]
    for (identity_id, name), indices in columns.items():
        scores = np.clip(similarities[:, indices].max(axis=1), -1, 1)
        for matches, score in zip(results, scores, strict=True):
            matches.append(IdentityMatch(identity_id, name, float(score)))
    return results


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
class _Track:
    at: datetime
    candidate: IdentityMatch
    match: IdentityMatch
    saved: datetime | None = None


class GalleryIdentifier:
    """One detector worker owns temporal state; encoder/cache may be shared."""

    def __init__(
        self,
        settings: IdentityConfig,
        catalog: IdentityCatalog,
        encoder: ImageEncoder,
        cache: EmbeddingCache,
    ):
        self.settings = settings
        self.catalog = catalog
        self.encoder = encoder
        self.cache = cache
        self.agreement = TrackAgreement(
            settings.min_observations, max_gap=max(5, settings.sample_interval * 3)
        )
        self._catalog: Catalog | None = None
        self._gallery = np.empty((0, encoder.dimension), dtype=np.float32)
        self._owners: tuple[tuple[str, str], ...] = ()
        self._tracks: dict[tuple[str, int | None], _Track] = {}

    def _refresh_gallery(self) -> Catalog:
        catalog = self.catalog.load()
        if catalog == self._catalog:
            return catalog
        samples = [
            (item, sample) for item in catalog.identities for sample in item.samples
        ]
        batches = [
            self.cache.encode(
                self.encoder,
                [
                    self.catalog.read_image(sample)
                    for _, sample in samples[start : start + 8]
                ],
            )
            for start in range(0, len(samples), 8)
        ]
        self._gallery = (
            np.concatenate(batches)
            if batches
            else np.empty((0, self.encoder.dimension), dtype=np.float32)
        )
        self._owners = tuple((item.id, item.name) for item, _ in samples)
        self._catalog = catalog
        self._tracks.clear()
        self.agreement.clear()
        return catalog

    def _match(self, images: list[NDArray[np.uint8]]) -> list[IdentityMatch]:
        if not images:
            return []
        if len(set(self._owners)) < 2:
            return [IdentityMatch() for _ in images]
        vectors = np.concatenate(
            [
                self.encoder.encode(images[start : start + 8])
                for start in range(0, len(images), 8)
            ]
        )
        return [
            choose_identity(
                scores, self.settings.min_similarity, self.settings.min_margin
            )
            for scores in distinct_identity_scores(vectors, self._gallery, self._owners)
        ]

    def identify(self, source: str, observation: Observation) -> Observation:
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
        candidates.update(zip(crops, self._match(list(crops.values())), strict=True))
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
                source, box.track_id, observation.date, candidates[index]
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
        current = {box.track_id for box in observation.boxes}
        for key, track in tuple(self._tracks.items()):
            same_source, track_id = key[0] == source, key[1]
            expired = same_source and (
                track_id not in current
                or (observation.date - track.at).total_seconds()
                > max(5, self.settings.sample_interval * 3)
                or observation.date < track.at
            )
            if expired:
                self.agreement.update(
                    source, track_id, observation.date, IdentityMatch()
                )
                del self._tracks[key]
