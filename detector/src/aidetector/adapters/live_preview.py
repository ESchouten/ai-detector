"""Publish bounded latest observations for viewers through the shared data folder."""

import base64
import hashlib
import json
import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, time
from uuid import uuid4

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.images import encode_jpeg
from aidetector.application.ports import PublishObservation
from aidetector.application.status import StatusEvent
from aidetector.domain.models import Observation

logger = logging.getLogger(__name__)
_FRAME_NAME = re.compile(r"[a-f0-9]{64}\.detector-[1-9]\d*\.(?:json|[a-f0-9]{32}\.tmp)")


@contextmanager
def _prepared_json(path: Path, record: dict) -> Iterator[Path]:
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(record, separators=(",", ":")), encoding="utf-8"
        )
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, record: dict) -> None:
    with _prepared_json(path, record) as temporary:
        temporary.replace(path)


class LivePreview:
    """Own one encoder thread; inference only replaces pending immutable observations."""

    def __init__(self, directory: Path, interval: float = 0.125):
        self.directory = directory
        self.interval = interval
        self.run_id = uuid4().hex
        self._sources: dict[str, str] = {}
        self._epochs: dict[str, str | None] = {}
        self._pending: dict[tuple[str, str], Observation] = {}
        self._published: dict[tuple[str, str], float] = {}
        self._active: set[str] = set()
        self._lock = Lock()
        self._stop = Event()
        self._failure: str | None = None
        self._heartbeat = 0.0

    def observer(self, rule_id: str, sources: Sequence[str]) -> PublishObservation:
        """Register configured sources before open(); return a nonblocking callback."""
        source_keys = {
            source: hashlib.sha256(source.encode()).hexdigest() for source in sources
        }
        self._sources.update(source_keys)

        def publish(source: str, observation: Observation) -> None:
            source_key = source_keys[source]
            with self._lock:
                if source_key in self._active and self._current(
                    source_key, observation
                ):
                    self._pending[(source_key, rule_id)] = observation

        return publish

    def source_status(self, event: StatusEvent) -> None:
        """Invalidate capture state synchronously; never perform I/O here."""
        if event.kind not in {"source_epoch", "offline"} or event.source is None:
            return
        key = self._sources.get(event.source)
        if key is None:
            return
        with self._lock:
            self._epochs[key] = (
                event.source_epoch if event.kind == "source_epoch" else None
            )
            self._pending = {
                k: value for k, value in self._pending.items() if k[0] != key
            }
            self._published = {
                k: value for k, value in self._published.items() if k[0] != key
            }
            self._heartbeat = 0

    def _current(self, source_key: str, observation: Observation) -> bool:
        if source_key not in self._epochs:
            # Finite sources and metadata-free callers retain their behavior.
            return True
        return (
            self._epochs[source_key] is not None
            and observation.capture is not None
            and observation.capture.epoch == self._epochs[source_key]
        )

    @contextmanager
    def open(self) -> Iterator[None]:
        thread = Thread(target=self._supervise, name="live-preview")
        thread.start()
        try:
            yield
        finally:
            self._stop.set()
            thread.join()

    def _supervise(self) -> None:
        try:
            frames = self.directory / "frames"
            frames.mkdir(parents=True, exist_ok=True)
            (self.directory / "leases").mkdir(exist_ok=True)
            for file in frames.iterdir():
                if _FRAME_NAME.fullmatch(file.name):
                    file.unlink(missing_ok=True)
            while not self._stop.is_set():
                try:
                    self._poll()
                except (OSError, MediaError) as error:
                    self._report_failure(error)
                self._stop.wait(self.interval)
        except Exception:
            logger.exception(
                "Live detection preview stopped; event detection continues"
            )
        finally:
            with self._lock:
                self._active.clear()
                self._pending.clear()
            self._remove_session()

    def _report_failure(self, error: Exception) -> None:
        message = str(error)
        if message != self._failure:
            logger.warning("Live detection preview unavailable: %s", message)
            self._failure = message

    def _remove_session(self) -> None:
        path = self.directory / "session.json"
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(session, dict) and session.get("runId") == self.run_id:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.exception("Could not remove live preview session")

    def _poll(self) -> None:
        active = {key for key in self._sources.values() if self._has_viewer(key)}
        now = monotonic()
        with self._lock:
            self._active = active
            epochs = self._epochs.copy()
            ready = {
                key: observation
                for key, observation in self._pending.items()
                if key[0] in active
                and now - self._published.get(key, -self.interval) >= self.interval
            }
            self._pending = {
                key: observation
                for key, observation in self._pending.items()
                if key[0] in active and key not in ready
            }
        if now - self._heartbeat >= 1.0:
            _atomic_json(
                self.directory / "session.json",
                {
                    "version": 1,
                    "runId": self.run_id,
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "sourceEpochs": epochs,
                },
            )
            self._heartbeat = now
        for (source_key, rule_id), observation in ready.items():
            if self._stop.is_set():
                break
            try:
                self._write_frame(source_key, rule_id, observation)
                self._failure = None
            except (OSError, MediaError) as error:
                self._report_failure(error)

    def _has_viewer(self, source_key: str) -> bool:
        try:
            lease = json.loads(
                (self.directory / "leases" / f"{source_key}.json").read_text(
                    encoding="utf-8"
                )
            )
            return (
                isinstance(lease, dict)
                and lease.get("version") == 1
                and isinstance(lease.get("expiresAt"), (int, float))
                and time() < lease["expiresAt"] <= time() + 30
            )
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return False

    def _write_frame(
        self, source_key: str, rule_id: str, observation: Observation
    ) -> None:
        with self._lock:
            if not self._current(source_key, observation):
                return
        height, width = observation.image.shape[:2]
        record = {
            "version": 1,
            "runId": self.run_id,
            "sourceKey": source_key,
            "ruleId": rule_id,
            "capturedAt": observation.date.isoformat(),
            "publishedAt": datetime.now(UTC).isoformat(),
            "image": {
                "width": width,
                "height": height,
                "jpeg": base64.b64encode(
                    encode_jpeg(observation.image, quality=75)
                ).decode("ascii"),
            },
            "boxes": [
                {
                    "x1": box.x1,
                    "y1": box.y1,
                    "x2": box.x2,
                    "y2": box.y2,
                    "label": box.label,
                    "confidence": box.confidence,
                    "trackId": box.track_id,
                    **(
                        {
                            "identity": {
                                "id": box.identity.identity_id,
                                "name": box.identity.name,
                                "similarity": box.identity.similarity,
                            }
                        }
                        if box.identity is not None
                        else {}
                    ),
                }
                for box in observation.boxes
            ],
        }
        if observation.capture is not None:
            record["capture"] = {
                "epoch": observation.capture.epoch,
                "sequence": observation.capture.sequence,
            }
        if not self._has_viewer(source_key) or self._stop.is_set():
            return
        path = self.directory / "frames" / f"{source_key}.{rule_id}.json"
        with _prepared_json(path, record) as temporary:
            # Encoding/writing can outlast a reconnect. Only the final rename holds
            # the state lock, so capture invalidation never waits on JPEG encoding.
            with self._lock:
                if self._current(source_key, observation) and not self._stop.is_set():
                    temporary.replace(path)
                    self._published[(source_key, rule_id)] = monotonic()
