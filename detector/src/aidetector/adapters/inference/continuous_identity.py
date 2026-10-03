"""One camera's optional anonymous continuous tracking and evidence boundary.

Subscribe at 0.5 seconds with retention four. Initial SAM work may briefly
queue frames: at most eight retained samples can be replayed anonymously until
a single-current-frame batch is reached. Afterwards any backlog resets the
camera. This operational jitter policy is not an accuracy guarantee.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import Event
from time import monotonic
from typing import cast
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.identity_control import IdentityReview, LiveIdentityControl
from aidetector.adapters.inference.cutie_runtime import CutieOutput, CutieRuntime
from aidetector.adapters.inference.identity_masks import foreground_boxes
from aidetector.adapters.inference.identity_startup import segment_startup
from aidetector.adapters.media.images import encode_jpeg
from aidetector.application.ports import Frames, ObjectDetector
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.domain.identity_continuity import IdentityContinuity, ObjectQuality
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import (
    BoundingBox,
    CaptureStamp,
    Frame,
    IdentityMatch,
    Observation,
)

_RETENTION = 4
_CATCHUP_LIMIT = 8
_GAP_SECONDS = 1.0


@dataclass(frozen=True)
class TrackEvidence:
    """Current unambiguous track evidence, not a persistent biological identity.

    The callback borrows read-only pixels. Retained copies must be bounded by
    its owner and keyed by source, capture epoch and the full target generation.
    A reset never reuses an instance ID. Mask p10 is segmentation quality only.
    """

    source: str
    capture: CaptureStamp
    target: LiveTarget
    box: BoundingBox
    mask_p10: float
    image: NDArray[np.uint8]
    analysis_index: int
    captured_at: datetime


@dataclass(frozen=True)
class ReviewSubject:
    box: BoundingBox
    review: IdentityReview


def ignore_evidence(evidence: TrackEvidence) -> None:
    pass


def ignore_reviews(reviews: tuple[ReviewSubject, ...]) -> None:
    pass


class ContinuousIdentityDetector:
    """Worker-owned, fixed-set tracker implementing the existing detector port.

    Bootstrap owns the raw detector/model context and the Cutie context. This
    adapter closes its camera state, not shared models. Raw inference must be
    stateless and configured for the desired individual-object class. No gallery
    is written, no new arrivals are enrolled, and slot IDs never become cow IDs.
    Source notifications and review requests are safe from their input threads;
    all other methods belong to the camera worker.
    """

    def __init__(
        self,
        source: str,
        raw: ObjectDetector,
        tracker: CutieRuntime,
        control: LiveIdentityControl,
        *,
        startup_weights: Path,
        label: str,
        publish_evidence: Callable[[TrackEvidence], None] = ignore_evidence,
        publish_reviews: Callable[[tuple[ReviewSubject, ...]], None] = ignore_reviews,
        report_status: ReportStatus = ignore_status,
        clock: Callable[[], float] = monotonic,
    ):
        self.source = source
        self._raw = raw
        self._tracker = tracker
        self._control = control
        self._weights = startup_weights
        self._label = label
        self._publish_evidence = publish_evidence
        self._publish_reviews = publish_reviews
        self._report = report_status
        self._clock = clock
        self._review_requested = Event()
        self._closed = False
        self._epoch: str | None = None
        self._previous: CaptureStamp | None = None
        self._shape: tuple[int, ...] | None = None
        self._policy: IdentityContinuity | None = None
        self._instances: dict[int, str] = {}
        self._history: OrderedDict[int, NDArray[np.uint8]] = OrderedDict()
        self._reviewable: set[str] = set()
        self._step = 0
        self._waiting_step = 0
        self._catching_up = False
        self._catchup_samples = 0
        self._last_status: tuple[str, str] | None = None

    def source_changed(self, epoch: str | None) -> None:
        self._control.source_changed(epoch)

    def request_review(self) -> None:
        """Coalesce requests; issue photos only from a fresh analyzed frame."""
        self._review_requested.set()

    def _status(self, kind: str, message: str) -> None:
        if (kind, message) != self._last_status:
            self._last_status = kind, message
            self._report(
                StatusEvent(
                    "identity_ready" if kind == "ready" else "identity_collecting",
                    self.source,
                    message,
                    source_epoch=self._epoch,
                )
            )

    def _reset(self, message: str) -> None:
        self._control.reset_tracking()
        self._tracker.reset()
        self._policy = None
        self._instances.clear()
        self._history.clear()
        self._reviewable.clear()
        self._review_requested.clear()
        self._previous = None
        self._shape = None
        self._step = self._waiting_step = self._catchup_samples = 0
        self._catching_up = False
        self._status("waiting", message)

    def maintain(self) -> None:
        """Called on idle source batches; stale pixels cannot accept a click."""
        if self._closed:
            return
        if self._epoch is not None and not self._control.source_is_current(self._epoch):
            self._reset("Camera disconnected; waiting for a fresh image")
            self._epoch = None
        elif (
            self._previous is not None
            and not self._catching_up
            and not 0 <= self._clock() - self._previous.monotonic_at < _GAP_SECONDS
        ):
            self._reset("Camera timing was interrupted; restarting anonymous tracking")

    def _current(self, frame: Frame, *, fresh: bool = False) -> bool:
        if frame.capture is None:
            raise ValueError("Continuous identity requires stamped live camera frames")
        if self._control.source_is_current(frame.capture.epoch):
            if (
                fresh
                and not 0 <= self._clock() - frame.capture.monotonic_at < _GAP_SECONDS
            ):
                self._reset("Camera result became stale; restarting anonymous tracking")
                return False
            return True
        self._reset("Camera changed during processing; waiting for its new image")
        self._epoch = None
        return False

    def _frames(self, batch: tuple[Frame, ...]) -> tuple[Frame, ...]:
        latest = batch[-1]
        if not self._current(latest):
            return ()
        assert latest.capture is not None
        if latest.capture.epoch != self._epoch:
            self._reset("Preparing anonymous camera tracks")
            if not self._control.change_epoch(latest.capture.epoch):
                return ()
            self._epoch = latest.capture.epoch
            return (latest,)
        if len(batch) >= _RETENTION:
            self._reset("Camera frame queue filled; restarting anonymous tracking")
            return (latest,)
        if not self._catching_up and len(batch) > 1:
            self._reset("Camera processing fell behind; restarting anonymous tracking")
            return (latest,)
        if self._catching_up:
            self._catchup_samples += len(batch)
            if self._catchup_samples > _CATCHUP_LIMIT:
                self._reset("Camera startup could not catch up; restarting tracking")
                return (latest,)
            if len(batch) == 1:
                self._catching_up = False
        return batch

    def _continuous(self, frame: Frame) -> bool:
        assert frame.capture is not None
        stamp = frame.capture
        previous = self._previous
        if previous is not None and (
            stamp.sequence <= previous.sequence
            or stamp.monotonic_at <= previous.monotonic_at
        ):
            self._reset("Old camera frame discarded; waiting for new evidence")
            return False
        if previous is not None and (
            stamp.epoch != previous.epoch
            or stamp.monotonic_at - previous.monotonic_at >= _GAP_SECONDS
            or frame.image.shape != self._shape
        ):
            self._reset("Camera continuity changed; restarting anonymous tracking")
        self._previous = stamp
        self._shape = frame.image.shape
        return True

    def detect(self, frames: Frames) -> dict[str, tuple[Observation, ...]]:
        if self._closed:
            raise RuntimeError("Continuous identity detector is closed")
        if not frames:
            self.maintain()
            return {}
        if tuple(frames) != (self.source,):
            raise ValueError("Continuous identity owns exactly its configured camera")
        result = None
        for frame in self._frames(frames[self.source]):
            require_fresh = self._policy is not None and not self._catching_up
            if not self._current(frame, fresh=require_fresh) or not self._continuous(
                frame
            ):
                return {}
            self._reviewable.clear()
            result = self._process(frame)
            if not self._current(frame):
                return {}
        return {self.source: (result,)} if result is not None else {}

    def _raw_observation(self, frame: Frame) -> Observation:
        observed = self._raw.detect({self.source: (frame,)})[self.source][-1]
        return replace(
            observed,
            boxes=tuple(box for box in observed.boxes if box.label == self._label),
            confidence={self._label: observed.confidence[self._label]}
            if self._label in observed.confidence
            else {},
        )

    def _initialize(self, frame: Frame, raw: Observation) -> CutieOutput | None:
        selected = segment_startup(self._weights, frame.image, raw.boxes)
        if not self._current(frame):
            return None
        count = len(selected.proposal_indices)
        if count > 8:
            self._status(
                "waiting", "Too many objects: use a camera view with at most eight"
            )
            return None
        if not count:
            self._status(
                "waiting", "Waiting for clear objects to begin anonymous tracking"
            )
            return None
        # Stable IDs follow original proposal order, not selection confidence order.
        order = np.argsort(selected.proposal_indices)
        seed = np.zeros(frame.image.shape[:2], dtype=np.int64)
        ids = tuple(range(1, count + 1))
        for object_id, index in zip(ids, order, strict=True):
            seed[selected.masks[index]] = object_id
        output = self._tracker.step(frame.image, mask=seed, object_ids=ids)
        if not self._current(frame):
            return None
        self._instances = {i: uuid4().hex for i in ids}
        for instance in self._instances.values():
            self._control.state.add(instance)
        self._policy = IdentityContinuity(ids)
        self._catching_up = True
        self._status(
            "waiting", "Anonymous tracks prepared; catching up with the camera"
        )
        return output

    def _process(self, frame: Frame) -> Observation | None:
        if self._policy is None:
            self._waiting_step += 1
            if self._waiting_step % 2 == 0:
                return None
            raw = self._raw_observation(frame)
            if not self._current(frame):
                return None
            output = self._initialize(frame, raw)
            if output is None:
                return None
        else:
            raw = self._raw_observation(frame) if self._step % 2 == 0 else None
            if not self._current(frame):
                return None
            output = self._tracker.step(frame.image)
        if not self._current(frame):
            return None
        step = self._step
        self._step += 1
        if raw is None:
            # Hold clicks for the next analyzed frame. Newly observed ambiguity
            # still invalidates their old photos immediately.
            self._control.invalidate_reviews(
                {
                    self._instances[item.object_id]
                    for item in output.objects
                    if item.p10_probability is None or item.p10_probability < 0.7
                }
            )
            return None
        return self._analyze(frame, output, raw, step // 2)

    def _analyze(
        self, frame: Frame, output: CutieOutput, raw: Observation, index: int
    ) -> Observation | None:
        assert self._policy is not None
        boxes = foreground_boxes(output.mask, self._label)

        def coverage(anchor: int, donor: int, receiver: int) -> float:
            previous = self._history[anchor] == donor
            area = int(np.count_nonzero(previous))
            return float(np.count_nonzero(previous & (output.mask == receiver)) / area)

        decision = self._policy.observe(
            index,
            tuple(
                ObjectQuality(i.object_id, i.area, i.p10_probability)
                for i in output.objects
            ),
            boxes,
            raw.boxes,
            coverage,
        )
        stored = output.mask.astype(np.uint8)
        stored.setflags(write=False)
        self._history[index] = stored
        while len(self._history) > 30:
            self._history.popitem(last=False)
        self._control.invalidate_reviews(
            {
                instance
                for i, instance in self._instances.items()
                if i not in decision.eligible_ids
            }
        )
        if self._catching_up:
            self._control.drain(set())
            return None
        if not self._current(frame, fresh=True):
            return None
        self._reviewable = {self._instances[i] for i in decision.eligible_ids}
        assert frame.capture is not None
        self._control.drain(
            self._reviewable,
            evidence_deadline=frame.capture.monotonic_at + _GAP_SECONDS,
        )
        if not self._current(frame, fresh=True):
            return None
        observation = Observation(
            frame.date,
            frame.image,
            raw.confidence,
            tuple(self._named(box, decision.eligible_ids) for box in boxes),
            frame.capture,
        )
        self._publish(frame, observation, output, index)
        if not self._current(frame, fresh=True):
            return None
        self._status("ready", f"Following {len(self._instances)} camera tracks")
        return observation

    def _named(self, box: BoundingBox, eligible: frozenset[int]) -> BoundingBox:
        identity = (
            self._control.state.identity(self._instances[box.track_id])
            if box.track_id in eligible
            else None
        )
        match = (
            IdentityMatch(identity.identity_id, identity.name)
            if identity
            else IdentityMatch()
        )
        return replace(box, identity=match)

    def _publish(
        self, frame: Frame, observation: Observation, output: CutieOutput, index: int
    ) -> None:
        assert frame.capture is not None
        qualities = {item.object_id: item for item in output.objects}
        subjects = []
        requested = self._review_requested.is_set()
        if requested:
            self._review_requested.clear()
        jpeg = encode_jpeg(frame.image) if requested and self._reviewable else None
        for box in observation.boxes:
            if not self._current(frame, fresh=True):
                return
            object_id = cast(int, box.track_id)
            instance = self._instances[object_id]
            if instance not in self._reviewable:
                continue
            target = self._control.state.target(instance)
            assert target is not None
            probability = qualities[object_id].p10_probability
            assert probability is not None
            self._publish_evidence(
                TrackEvidence(
                    self.source,
                    frame.capture,
                    target,
                    box,
                    probability,
                    frame.image,
                    analysis_index=index,
                    captured_at=frame.date,
                )
            )
            if jpeg is not None and self._current(frame, fresh=True):
                review = self._review(frame, instance, jpeg)
                if review is None:
                    return
                subjects.append(ReviewSubject(box, review))
        if subjects and self._current(frame, fresh=True):
            self._publish_reviews(tuple(subjects))

    def _review(
        self, frame: Frame, instance: str, jpeg: bytes
    ) -> IdentityReview | None:
        assert frame.capture is not None
        try:
            return self._control.publish_review(instance, frame.capture, jpeg)
        except ValueError:
            # Capture may supersede the frame after the pre-publication check.
            # Other invalid-state errors remain programming failures.
            if not self._current(frame):
                return None
            raise

    def close(self) -> None:
        if not self._closed:
            self._reset("Anonymous camera tracking stopped")
            self._control.close()
            self._closed = True
