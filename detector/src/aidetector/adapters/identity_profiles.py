"""Bounded anonymous observation evidence, separate from the confirmed herd.

This I/O boundary assigns no animal identity and performs no matching. The
caller selects useful current observations; this store keeps at most sixteen
recent candidates per scoped instance. Old candidates expire or are evicted
automatically. Shared full-frame JPEGs preserve head/context for later inspection.
Facts distinguish source-resolution from analysis-only inputs and record the
analysis shape. JPEGs are lossy: their digest differs from original BGR pixels.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.media.images import encode_jpeg
from aidetector.adapters.operational_status import source_key
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import BoundingBox, CaptureStamp

_MAX_FRAME_BYTES = 32 * 1024**2
_MAX_CACHE_BYTES = 48 * 1024**2


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _pixel_digest(image: NDArray[np.uint8]) -> str:
    value = hashlib.sha256(str((image.shape, image.dtype)).encode())
    value.update(image.tobytes())
    return value.hexdigest()


@dataclass(frozen=True)
class _ImageCache:
    key: tuple[str, str, str, int]
    image: NDArray[np.uint8]
    pixels_sha256: str
    encoded_sha256: str
    jpeg: bytes


class IdentityProfileStore:
    """One process owns this store; a lock permits calls from camera workers.

    ``directory`` is the identity data directory. Only its own ``automatic``
    child is touched. A profile groups run/source/epoch/instance/generation,
    never separate visits or biological identities. Target revisions are facts,
    not reasons to merge or split the observation instance.

    Quotas apply to the persistent SQLite file, including metadata. Its ordinary
    temporary rollback journal can require additional disk space while writing.
    Expiry runs on opening, saving, reading and explicit maintenance; no thread
    or model is created here. Callers own cadence and report I/O failures.
    """

    def __init__(
        self,
        directory: Path,
        run_id: str,
        *,
        max_candidates: int = 16,
        max_profiles: int = 500,
        max_bytes: int = 256 * 1024**2,
        max_age: timedelta = timedelta(days=7),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if (
            max_candidates < 1
            or max_profiles < 1
            or max_bytes < 128 * 1024
            or max_age.total_seconds() <= 0
        ):
            raise ValueError("Positive bounded profile retention is required")
        self.directory = directory / "automatic"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.max_candidates, self.max_profiles = max_candidates, max_profiles
        self.max_bytes, self.max_age = max_bytes, max_age.total_seconds()
        self._clock = clock
        self._lock = Lock()
        self._last_image: _ImageCache | None = None
        self._path = self.directory / "profiles.sqlite"
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA auto_vacuum=FULL")
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
            self._db.execute(f"PRAGMA max_page_count={max_bytes // page_size}")
            if self._db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise sqlite3.DatabaseError(
                    "Unsupported anonymous profile store version"
                )
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, jpeg BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    image_id TEXT NOT NULL REFERENCES images(id),
                    sequence INTEGER NOT NULL, monotonic_at REAL NOT NULL,
                    saved_at REAL NOT NULL, facts TEXT NOT NULL,
                    UNIQUE(profile_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS candidates_age ON candidates(saved_at, id);
                PRAGMA user_version=1;
            """)
            self.maintain()
        except BaseException:
            self._db.close()
            raise

    def _unused(self) -> None:
        self._db.execute(
            "DELETE FROM images WHERE id NOT IN (SELECT image_id FROM candidates)"
        )
        self._db.execute(
            "DELETE FROM profiles WHERE id NOT IN (SELECT profile_id FROM candidates)"
        )

    def _expire(self, now: float) -> None:
        self._db.execute(
            "DELETE FROM candidates WHERE saved_at < ?", (now - self.max_age,)
        )
        self._unused()
        self._db.execute(
            """
            DELETE FROM candidates WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY profile_id ORDER BY saved_at DESC,sequence DESC,id DESC
                    ) AS position FROM candidates
                ) WHERE position > ?
            )
        """,
            (self.max_candidates,),
        )
        self._db.execute(
            "DELETE FROM profiles WHERE id IN (SELECT id FROM profiles ORDER BY last_seen DESC,id DESC LIMIT -1 OFFSET ?)",
            (self.max_profiles,),
        )
        self._unused()
        while self._bytes() > self.max_bytes:
            if not self._db.execute("SELECT 1 FROM candidates LIMIT 1").fetchone():
                raise OSError("Profile metadata exceeds the storage quota")
            self._db.execute(
                "DELETE FROM candidates WHERE id=(SELECT id FROM candidates ORDER BY saved_at,id LIMIT 1)"
            )
            self._unused()

    def maintain(self) -> None:
        with self._lock:
            with self._db:
                self._expire(self._clock().timestamp())
            # SQLite cannot lower the page cap below the current file size.
            # FULL auto-vacuum has now committed quota eviction and truncated it.
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
            self._db.execute(f"PRAGMA max_page_count={self.max_bytes // page_size}")

    def _bytes(self) -> int:
        pages = self._db.execute("PRAGMA page_count").fetchone()[0]
        free = self._db.execute("PRAGMA freelist_count").fetchone()[0]
        size = self._db.execute("PRAGMA page_size").fetchone()[0]
        return (pages - free) * size

    def _room(
        self, profile: str, metadata_bytes: int, image_id: str, image_bytes: int
    ) -> bool:
        if metadata_bytes + image_bytes + 64 * 1024 > self.max_bytes:
            return False
        exists = self._db.execute(
            "SELECT 1 FROM profiles WHERE id=?", (profile,)
        ).fetchone()
        count = self._db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if not exists and count >= self.max_profiles:
            self._db.execute(
                "DELETE FROM profiles WHERE id=(SELECT id FROM profiles ORDER BY last_seen,id LIMIT 1)"
            )
        self._db.execute(
            "DELETE FROM candidates WHERE id IN (SELECT id FROM candidates WHERE profile_id=? ORDER BY saved_at DESC,sequence DESC,id DESC LIMIT -1 OFFSET ?)",
            (profile, self.max_candidates - 1),
        )
        self._unused()

        def required_bytes() -> int:
            shared = self._db.execute(
                "SELECT 1 FROM images WHERE id=?", (image_id,)
            ).fetchone()
            return metadata_bytes + (0 if shared else image_bytes) + 16 * 1024

        while self._bytes() + required_bytes() > self.max_bytes:
            if not self._db.execute("SELECT 1 FROM candidates LIMIT 1").fetchone():
                return False
            self._db.execute(
                "DELETE FROM candidates WHERE id=(SELECT id FROM candidates ORDER BY saved_at,id LIMIT 1)"
            )
            self._unused()
        return True

    def save(
        self,
        source: str,
        capture: CaptureStamp,
        target: LiveTarget,
        captured_at: datetime,
        box: BoundingBox,
        mask_p10: float,
        image: NDArray[np.uint8],
        *,
        episode_id: str,
        analysis_index: int,
        accept: Callable[[], bool] | None = None,
        analysis_shape: tuple[int, ...] | None = None,
        image_resolution: Literal["analysis", "source"] = "analysis",
    ) -> str | None:
        """Save one selected fact, or skip a stale/oversized observation.

        Caller has already applied tracking quality and a bounded sampling
        cadence. Quality is retained as evidence, never converted to identity
        confidence. Replaying the exact same observation is idempotent. The
        optional acceptance check runs after encoding, immediately before
        storage mutation; a source change during encoding can reject the fact.
        Already accepted historical facts are not current tracking state.
        ``image_resolution`` describes the supplied pixels, never a guess from
        their dimensions. Legacy callers default to explicit analysis-only facts.
        """
        if image.nbytes > _MAX_FRAME_BYTES or (accept is not None and not accept()):
            return None
        analyzed = list(image.shape if analysis_shape is None else analysis_shape)
        scope = {
            "run_id": self.run_id,
            "source_key": source_key(source),
            "epoch": capture.epoch,
            "instance_id": target.instance_id,
            "generation": target.generation,
        }
        profile = _digest(scope)[:32]
        frame_key = (
            scope["run_id"],
            scope["source_key"],
            capture.epoch,
            capture.sequence,
        )
        with self._lock, self._db:
            cached = self._last_image
            reusable = (
                cached is not None and cached.key == frame_key and cached.image is image
            )
            pixels = cached.pixels_sha256 if reusable else _pixel_digest(image)
            now = self._clock().timestamp()
            self._expire(now)
            previous = self._db.execute(
                "SELECT id,sequence,monotonic_at,facts FROM candidates WHERE profile_id=? ORDER BY sequence DESC LIMIT 1",
                (profile,),
            ).fetchone()
            if previous and capture.sequence <= previous[1]:
                old = json.loads(previous[3])
                return (
                    previous[0]
                    if capture.sequence == previous[1]
                    and pixels == old["original_pixels_sha256"]
                    and capture.monotonic_at == previous[2]
                    and old["episode_id"] == episode_id
                    and old["analysis_index"] == analysis_index
                    and old["target_revision"] == target.revision
                    and old["captured_at"] == captured_at.isoformat()
                    and old["box"] == [box.x1, box.y1, box.x2, box.y2]
                    and old["mask_p10"] == mask_p10
                    and old.get("analysis_shape", old["image_shape"]) == analyzed
                    and old.get("image_resolution", "analysis") == image_resolution
                    else None
                )
            if previous and capture.monotonic_at <= previous[2]:
                return None
            if not reusable:
                encoded = encode_jpeg(image, quality=95)
                if image.nbytes + len(encoded) > _MAX_CACHE_BYTES:
                    self._last_image = None
                    return None
                cached = _ImageCache(
                    frame_key,
                    image,
                    pixels,
                    hashlib.sha256(encoded).hexdigest(),
                    encoded,
                )
                self._last_image = cached
            assert cached is not None
            if accept is not None and not accept():
                self._last_image = None
                return None
            encoded_sha, encoded = cached.encoded_sha256, cached.jpeg
            sample = _digest((profile, capture.sequence, pixels))[:32]
            facts = {
                "version": 1,
                "id": sample,
                "profile_id": profile,
                **scope,
                "status": "anonymous_observation_not_biological_identity",
                "captured_at": captured_at.isoformat(),
                "captured_at_timezone": "naive_local"
                if captured_at.utcoffset() is None
                else "explicit_offset",
                "capture_sequence": capture.sequence,
                "capture_monotonic_at": capture.monotonic_at,
                "target_revision": target.revision,
                "episode_id": episode_id,
                "analysis_index": analysis_index,
                "original_pixels_sha256": pixels,
                "image_shape": list(image.shape),
                "analysis_shape": analyzed,
                "image_resolution": image_resolution,
                "image_encoding": "source-resolution-jpeg-quality95"
                if image_resolution == "source"
                else "full-analyzed-resolution-jpeg-quality95",
                "encoded_sha256": encoded_sha,
                "box": [box.x1, box.y1, box.x2, box.y2],
                "temporary_track_id": box.track_id,
                "mask_p10": mask_p10,
            }
            serialized = json.dumps(facts, sort_keys=True)
            if not self._room(profile, len(serialized), encoded_sha, len(encoded)):
                self._last_image = None
                return None
            self._db.execute(
                "INSERT OR IGNORE INTO images VALUES (?,?)", (encoded_sha, encoded)
            )
            self._db.execute(
                "INSERT INTO profiles VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen",
                (profile, json.dumps(scope, sort_keys=True), now),
            )
            self._db.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?,?,?)",
                (
                    sample,
                    profile,
                    encoded_sha,
                    capture.sequence,
                    capture.monotonic_at,
                    now,
                    serialized,
                ),
            )
            return sample

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        """Return bounded immutable-fact copies; there are no animal labels."""
        with self._lock, self._db:
            self._expire(self._clock().timestamp())
            return tuple(
                json.loads(row[0])
                for row in self._db.execute(
                    "SELECT facts FROM candidates ORDER BY saved_at,id"
                )
            )

    def image(self, candidate_id: str) -> bytes | None:
        with self._lock, self._db:
            self._expire(self._clock().timestamp())
            row = self._db.execute(
                "SELECT jpeg,images.id FROM candidates JOIN images ON images.id=candidates.image_id WHERE candidates.id=?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            encoded = bytes(row[0])
            if hashlib.sha256(encoded).hexdigest() != row[1]:
                raise OSError("Anonymous evidence image digest mismatch")
            return encoded

    def usage(self) -> dict[str, int]:
        with self._lock:
            return {
                **{
                    name: self._db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("profiles", "candidates", "images")
                },
                "database_bytes": self._path.stat().st_size,
            }

    def close(self) -> None:
        with self._lock:
            self._last_image = None
            self._db.close()
