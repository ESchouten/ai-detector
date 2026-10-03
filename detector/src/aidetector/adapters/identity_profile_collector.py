"""Select bounded anonymous evidence from one continuously analyzed camera.

There is no image queue, biological identity, or cross-episode matching here.
Capture notifications only update a small locked authority token. The camera
worker owns sampling state and synchronous, occasional storage operations.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from aidetector.adapters.identity_profiles import IdentityProfileStore
from aidetector.adapters.media import MediaError
from aidetector.adapters.operational_status import source_key
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import BoundingBox, CaptureStamp

if TYPE_CHECKING:
    from aidetector.adapters.inference.continuous_identity import TrackEvidence

logger = logging.getLogger(__name__)
_MAX_INSTANCES = 8
_SAMPLE_SECONDS = 10.0
_IDLE_SECONDS = 3.0
_MAINTAIN_SECONDS = 60.0


def _native_box(evidence: TrackEvidence) -> BoundingBox:
    """Cover the source pixels represented by inclusive analysis-mask bounds."""
    assert evidence.native_image is not None
    height, width = evidence.native_image.shape[:2]
    analysis_height, analysis_width = evidence.image.shape[:2]
    box = evidence.box
    return replace(
        box,
        x1=max(0, box.x1 * width // analysis_width),
        y1=max(0, box.y1 * height // analysis_height),
        x2=min(width - 1, ((box.x2 + 1) * width - 1) // analysis_width),
        y2=min(height - 1, ((box.y2 + 1) * height - 1) // analysis_height),
    )


@dataclass
class _Episode:
    target: LiveTarget
    episode_id: str
    index: int
    capture: CaptureStamp
    consecutive: int = 1
    saved_at: float = float("-inf")


class IdentityProfileCollector:
    """One camera worker selects facts and owns its lazily opened store.

    Call ``source_changed`` from the capture notification fanout before new
    pixels are published. All other methods belong to the camera worker. Three
    consecutive eligible analysis steps are required, followed by at most one
    save per ten seconds per instance. An analysis gap starts a new episode;
    target generations and camera epochs never share an episode. Eight small
    episode records and one capture stamp are the entire retained worker state.

    The store shares one bounded full-frame JPEG cache across camera instances.
    This collector keeps no pixel references and starts no background work.
    Expected persistence errors, including initial open failures, are observable
    and retry after sixty seconds; detection continues. ``close`` releases both
    selection state and the owned store.
    """

    def __init__(
        self,
        directory: Path,
        run_id: str,
        source: str,
        *,
        report_status: ReportStatus = ignore_status,
        clock: Callable[[], float] = monotonic,
    ):
        self._directory, self._run_id, self._source = directory, run_id, source
        self._store: IdentityProfileStore | None = None
        self._report, self._clock = report_status, clock
        self._lock = Lock()
        self._epoch: str | None = None
        self._revision = 0
        self._closed = False
        self._applied_revision = -1
        self._episodes: dict[str, _Episode] = {}
        self._frame: CaptureStamp | None = None
        self._index = -1
        self._generation_floor = 0
        self._latest_generation = 0
        self._retry_at = self._maintenance_at = float("-inf")
        self._failed = False

    def source_changed(self, epoch: str | None) -> None:
        """Authoritative capture notification; never waits for disk/JPEG work."""
        with self._lock:
            if epoch != self._epoch:
                self._epoch = epoch
                self._revision += 1

    def _authority(self) -> tuple[str | None, int]:
        with self._lock:
            return (None if self._closed else self._epoch), self._revision

    def _synchronize(self) -> tuple[str | None, int]:
        authority = self._authority()
        if authority[1] != self._applied_revision:
            self._episodes.clear()
            self._frame = None
            self._index = -1
            self._generation_floor = self._latest_generation = 0
            self._applied_revision = authority[1]
        return authority

    def _ordered(self, evidence: TrackEvidence) -> bool:
        previous = self._frame
        stamp, index = evidence.capture, evidence.analysis_index
        if previous is not None:
            if stamp.sequence == previous.sequence:
                return stamp == previous and index == self._index
            if (
                stamp.sequence < previous.sequence
                or stamp.monotonic_at <= previous.monotonic_at
            ):
                return False
            if index <= self._index:
                # A worker reset restarts analysis indices but not capture
                # sequence or LiveIdentityState's generation counter.
                self._episodes.clear()
                self._generation_floor = self._latest_generation
        self._frame, self._index = stamp, index
        return True

    def _episode(self, evidence: TrackEvidence) -> _Episode | None:
        target = evidence.target
        if target.generation <= self._generation_floor:
            return None
        previous = self._episodes.get(target.instance_id)
        if previous is not None and (
            target.generation < previous.target.generation
            or (
                target.generation == previous.target.generation
                and evidence.analysis_index <= previous.index
            )
        ):
            return None
        saved_at = (
            previous.saved_at
            if previous is not None and target.generation == previous.target.generation
            else float("-inf")
        )
        consecutive = (
            previous is not None
            and target.generation == previous.target.generation
            and evidence.analysis_index == previous.index + 1
            and evidence.capture.monotonic_at - previous.capture.monotonic_at
            < _IDLE_SECONDS
        )
        if previous is None and len(self._episodes) >= _MAX_INSTANCES:
            oldest = min(
                self._episodes, key=lambda k: self._episodes[k].capture.sequence
            )
            del self._episodes[oldest]
        current = _Episode(
            target,
            previous.episode_id
            if consecutive and previous is not None
            else uuid4().hex,
            evidence.analysis_index,
            evidence.capture,
            min(3, previous.consecutive + 1)
            if consecutive and previous is not None
            else 1,
            saved_at,
        )
        self._episodes[target.instance_id] = current
        self._latest_generation = max(self._latest_generation, target.generation)
        return current

    def _storage(self) -> IdentityProfileStore:
        if self._store is None:
            self._store = IdentityProfileStore(self._directory, self._run_id)
        return self._store

    def _close_store(self) -> None:
        if self._store is not None:
            store, self._store = self._store, None
            store.close()

    def _failure(self, error: Exception, now: float) -> None:
        try:
            self._close_store()
        except sqlite3.Error:
            pass
        self._failed = True
        self._retry_at = now + _MAINTAIN_SECONDS
        logger.warning(
            "Anonymous evidence storage unavailable for source %s: %s",
            source_key(self._source)[:12],
            type(error).__name__,
        )
        self._report(
            StatusEvent(
                "notice",
                self._source,
                "Camera tracking continues, but anonymous evidence could not be saved; retrying in one minute",
                source_epoch=self._authority()[0],
            )
        )

    def __call__(self, evidence: TrackEvidence) -> None:
        if evidence.source != self._source:
            raise ValueError("Anonymous evidence belongs to a different camera")
        authority = self._synchronize()
        now = self._clock()
        if (
            authority[0] != evidence.capture.epoch
            or not 0 <= now - evidence.capture.monotonic_at < 1.0
            or not self._ordered(evidence)
        ):
            return
        current = self._episode(evidence)
        if (
            current is None
            or current.consecutive < 3
            or evidence.capture.monotonic_at - current.saved_at < _SAMPLE_SECONDS
            or now < self._retry_at
        ):
            return

        def accept() -> bool:
            return (
                self._authority() == authority
                and 0 <= self._clock() - evidence.capture.monotonic_at < 1.0
            )

        try:
            saved = self._storage().save(
                evidence.source,
                evidence.capture,
                evidence.target,
                evidence.captured_at,
                evidence.box
                if evidence.native_image is None
                else _native_box(evidence),
                evidence.mask_p10,
                evidence.image
                if evidence.native_image is None
                else evidence.native_image,
                episode_id=current.episode_id,
                analysis_index=evidence.analysis_index,
                accept=accept,
                analysis_shape=evidence.image.shape,
                image_resolution="analysis"
                if evidence.native_image is None
                else "source",
            )
        except (OSError, sqlite3.Error, MediaError) as error:
            self._failure(error, self._clock())
            return
        if saved is not None:
            current.saved_at = evidence.capture.monotonic_at
            if self._failed:
                self._failed = False
                logger.info(
                    "Anonymous evidence storage recovered for source %s",
                    source_key(self._source)[:12],
                )

    def maintain(self) -> None:
        """Expire idle selection state and occasionally enforce shared retention."""
        self._synchronize()
        now = self._clock()
        self._episodes = {
            key: value
            for key, value in self._episodes.items()
            if 0 <= now - value.capture.monotonic_at < _IDLE_SECONDS
        }
        if self._closed or now < max(self._maintenance_at, self._retry_at):
            return
        self._maintenance_at = now + _MAINTAIN_SECONDS
        try:
            self._storage().maintain()
        except (OSError, sqlite3.Error) as error:
            self._failure(error, now)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._epoch = None
            self._revision += 1
        self._synchronize()
        self._close_store()
