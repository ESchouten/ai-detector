"""Bounded live-name commands; only the camera worker mutates identity state.

The owner publishes an exact analyzed JPEG, then drains commands between frames.
The input thread only submits validated commands. Saved historical herd photos
are a different operation: they cannot be used to name a current instance.
"""

import logging
from collections import OrderedDict, deque
from collections.abc import Callable, Set
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aidetector.adapters.identity_catalog import Identifier, IdentityCatalog
from aidetector.domain.live_identity import LiveIdentityState, LiveTarget
from aidetector.domain.models import CaptureStamp

logger = logging.getLogger(__name__)


class ConfirmLiveIdentity(BaseModel):
    """The one supported live-name command on the launcher's control pipe."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1]
    command: Literal["confirm_identity"]
    request_id: Identifier
    run_id: Identifier
    source_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    epoch: Identifier
    snapshot_id: Identifier
    identity_id: Identifier
    catalog_revision: Annotated[int, Field(ge=0)]


@dataclass(frozen=True)
class IdentityAcknowledgement:
    request_id: str
    status: Literal[
        "confirmed", "stale", "identity_in_use", "catalog_changed", "unavailable"
    ]
    identity_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class IdentityReview:
    """Immutable pixels and instance version shown together in a confirmation UI."""

    snapshot_id: str
    capture: CaptureStamp
    target: LiveTarget
    jpeg: bytes
    expires_at: float


class LiveIdentityControl:
    """Control boundary for one run and camera, with explicit worker ownership.

    ``submit`` is safe from the input thread. Other methods run on the camera
    worker. ``report`` must serialize acknowledgements with the status writer.
    Request deadlines prevent an old queued click applying after a web timeout.
    Repeated IDs replay the original result and never perform a second mutation.
    """

    def __init__(
        self,
        run_id: str,
        source_key: str,
        state: LiveIdentityState,
        catalog: IdentityCatalog,
        report: Callable[[IdentityAcknowledgement], None],
        *,
        clock: Callable[[], float] = monotonic,
    ):
        self.run_id = run_id
        self.source_key = source_key
        self.state = state
        self._catalog = catalog
        self._report = report
        self._clock = clock
        self._epoch: str | None = None
        self._source_epoch: str | None = None
        self._snapshots: OrderedDict[str, IdentityReview] = OrderedDict()
        self._pending: deque[tuple[ConfirmLiveIdentity, float]] = deque()
        self._requests: dict[str, ConfirmLiveIdentity] = {}
        self._completed: OrderedDict[str, IdentityAcknowledgement] = OrderedDict()
        self._lock = Lock()
        self._closed = False

    def source_changed(self, epoch: str | None) -> None:
        """Capture thread announces reconnect/offline without mutating tracking."""
        with self._lock:
            self._source_epoch = epoch

    def source_is_current(self, epoch: str) -> bool:
        with self._lock:
            return not self._closed and epoch == self._source_epoch

    def change_epoch(self, epoch: str) -> bool:
        """The worker begins a current epoch and also resets its tracking core.

        False means this frame was superseded while waiting for inference. The
        capture notification is authoritative; old frames cannot reopen it.
        """
        with self._lock:
            if self._closed or epoch != self._source_epoch:
                return False
            if self._epoch != epoch:
                self.state.reset()
                self._snapshots.clear()
                self._epoch = epoch
            return True

    def publish_review(
        self, instance_id: str, capture: CaptureStamp, jpeg: bytes
    ) -> IdentityReview:
        target = self.state.target(instance_id)
        if (
            target is None
            or capture.epoch != self._epoch
            or not self.source_is_current(capture.epoch)
        ):
            raise ValueError("A review needs an active instance in the current epoch")
        now = self._clock()
        self._expire_reviews(now)
        review = IdentityReview(uuid4().hex, capture, target, jpeg, now + 120)
        self._snapshots[review.snapshot_id] = review
        while len(self._snapshots) > 32:
            self._snapshots.popitem(last=False)
        return review

    def submit(self, command: ConfirmLiveIdentity) -> None:
        """Accept a parsed command without touching models, files or domain state."""
        reply = None
        with self._lock:
            previous = self._requests.get(command.request_id)
            if previous is not None:
                reply = (
                    self._completed.get(command.request_id)
                    if previous == command
                    else IdentityAcknowledgement(command.request_id, "stale")
                )
            elif (
                self._closed
                or command.run_id != self.run_id
                or command.source_key != self.source_key
                or len(self._pending) >= 16
            ):
                reply = IdentityAcknowledgement(command.request_id, "unavailable")
            else:
                self._requests[command.request_id] = command
                self._pending.append((command, self._clock() + 5))
        if reply is not None:
            self._report(reply)

    def drain(self, reviewable: Set[str]) -> None:
        """Apply clicks only to currently unambiguous instances, between frames."""
        self._expire_reviews(self._clock())
        with self._lock:
            pending = tuple(self._pending)
            self._pending.clear()
        for command, deadline in pending:
            reply = (
                IdentityAcknowledgement(command.request_id, "unavailable")
                if self._clock() >= deadline
                else self._confirm(command, reviewable, deadline)
            )
            self._finish(reply)

    def close(self) -> None:
        """Fail waiting clicks on shutdown; an input thread cannot reopen this run."""
        with self._lock:
            self._closed = True
            self._source_epoch = None
            pending = tuple(self._pending)
            self._pending.clear()
        for command, _ in pending:
            self._finish(IdentityAcknowledgement(command.request_id, "unavailable"))
        self._snapshots.clear()
        self.state.reset()

    def _confirm(
        self, command: ConfirmLiveIdentity, reviewable: Set[str], deadline: float
    ) -> IdentityAcknowledgement:
        review = self._snapshots.get(command.snapshot_id)
        if (
            review is None
            or command.epoch != self._epoch
            or not self.source_is_current(command.epoch)
            or review.capture.epoch != command.epoch
            or review.target.instance_id not in reviewable
            or self.state.target(review.target.instance_id) != review.target
        ):
            return IdentityAcknowledgement(command.request_id, "stale")
        try:
            catalog = self._catalog.load()
        except (OSError, ValidationError):
            logger.exception("Live naming could not read the confirmed herd")
            return IdentityAcknowledgement(command.request_id, "unavailable")
        identity = next(
            (item for item in catalog.identities if item.id == command.identity_id),
            None,
        )
        if catalog.revision != command.catalog_revision or identity is None:
            return IdentityAcknowledgement(command.request_id, "catalog_changed")
        # Catalog I/O and inference can outlast the camera connection. Order the
        # final mutation against capture notifications without holding this lock
        # over I/O or GPU work. Only the worker touches domain state.
        with self._lock:
            if self._closed or command.epoch != self._source_epoch:
                return IdentityAcknowledgement(command.request_id, "stale")
            now = self._clock()
            if now >= deadline:
                return IdentityAcknowledgement(command.request_id, "unavailable")
            if now >= review.expires_at:
                return IdentityAcknowledgement(command.request_id, "stale")
            result = self.state.confirm(review.target, identity.id, identity.name)
        return IdentityAcknowledgement(
            command.request_id,
            result.status,
            identity.id if result.status == "confirmed" else None,
            identity.name if result.status == "confirmed" else None,
        )

    def _finish(self, reply: IdentityAcknowledgement) -> None:
        with self._lock:
            self._completed[reply.request_id] = reply
            while len(self._completed) > 128:
                expired, _ = self._completed.popitem(last=False)
                del self._requests[expired]
        self._report(reply)

    def _expire_reviews(self, now: float) -> None:
        while self._snapshots:
            oldest = next(iter(self._snapshots.values()))
            if oldest.expires_at > now:
                break
            self._snapshots.popitem(last=False)
