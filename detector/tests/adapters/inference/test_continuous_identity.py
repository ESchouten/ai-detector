"""Camera-worker behavior through real control/policy, without model downloads."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.identity_control import (
    ConfirmLiveIdentity,
    LiveIdentityControl,
)
from aidetector.adapters.inference import continuous_identity
from aidetector.adapters.inference.continuous_identity import ContinuousIdentityDetector
from aidetector.adapters.inference.cutie_runtime import CutieOutput, MaskEvidence
from aidetector.adapters.inference.identity_masks import SeedSelection
from aidetector.domain.live_identity import LiveIdentityState
from aidetector.domain.models import BoundingBox, CaptureStamp, Frame, Observation

SOURCE = "camera"
EPOCH = "a" * 32
COW = "c" * 32


@dataclass
class Clock:
    now: float = 10

    def __call__(self):
        return self.now


class RawDetector:
    def __init__(self):
        self.calls = []
        self.hook = None
        self.boxes = (BoundingBox(1, 1, 9, 9, "cow", 0.8),)

    def detect(self, frames):
        frame = frames[SOURCE][-1]
        self.calls.append(frame)
        if self.hook:
            self.hook()
        return {
            SOURCE: (
                Observation(
                    frame.date,
                    frame.image,
                    {box.label: box.confidence for box in self.boxes},
                    self.boxes,
                    frame.capture,
                ),
            )
        }


class Tracker:
    def __init__(self):
        self.calls = []
        self.resets = 0
        self.mask = None
        self.hook = None
        self.probability = 0.9

    def reset(self):
        self.resets += 1
        self.mask = None

    def step(self, image, *, mask=None, object_ids=()):
        self.calls.append((image, object_ids))
        if mask is not None:
            self.mask = mask.copy()
            self.mask.setflags(write=False)
        if self.hook:
            self.hook()
        return CutieOutput(
            self.mask,
            tuple(
                MaskEvidence(
                    int(i),
                    int(np.count_nonzero(self.mask == i)),
                    self.probability,
                    self.probability,
                )
                for i in np.unique(self.mask)
                if i
            ),
        )


@pytest.fixture
def camera(tmp_path, monkeypatch):
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": 0,
                "identities": [{"id": COW, "name": "Bella", "samples": []}],
            }
        )
    )
    clock, raw, tracker = Clock(), RawDetector(), Tracker()
    state = LiveIdentityState()
    control = LiveIdentityControl(
        "1" * 32,
        "2" * 64,
        state,
        IdentityCatalog(tmp_path),
        lambda _: None,
        clock=clock,
    )
    evidence, reviews, statuses, starts = [], [], [], []

    def segment(weights, image, proposals):
        starts.append(image)
        masks = np.zeros((len(proposals), *image.shape[:2]), bool)
        for i, box in enumerate(proposals):
            masks[i, box.y1 : box.y2 + 1, box.x1 : box.x2 + 1] = True
        masks.setflags(write=False)
        return SeedSelection(
            tuple(range(len(proposals))), masks, tuple("selected" for _ in proposals)
        )

    monkeypatch.setattr(continuous_identity, "segment_startup", segment)
    owner = ContinuousIdentityDetector(
        SOURCE,
        raw,
        tracker,
        control,
        startup_weights=Path("unused.pt"),
        label="cow",
        publish_evidence=evidence.append,
        publish_reviews=reviews.append,
        report_status=statuses.append,
        clock=clock,
    )
    owner.source_changed(EPOCH)
    return owner, control, clock, raw, tracker, evidence, reviews, statuses, starts


def frame(second, *, epoch=EPOCH, shape=(20, 30, 3), sequence=None):
    image = np.full(shape, int(second * 10) % 255, np.uint8)
    image.setflags(write=False)
    return Frame(
        datetime(2026, 10, 3) + timedelta(seconds=second),
        image,
        CaptureStamp(
            epoch, int(second * 30) if sequence is None else sequence, 10 + second
        ),
    )


def send(camera, *seconds, **kwargs):
    owner, _, clock, *_ = camera
    samples = tuple(frame(second, **kwargs) for second in seconds)
    clock.now = samples[-1].capture.monotonic_at
    return owner.detect({SOURCE: samples})


def ready(camera):
    assert send(camera, 0) == {}
    assert send(camera, 0.5) == {}
    return send(camera, 1)[SOURCE][0]


def test_current_anonymous_evidence_and_requested_photo_have_exact_source(camera):
    owner, control, _, raw, tracker, evidence, reviews, *_ = camera
    result = ready(camera)
    assert len(raw.calls) == 2 and len(tracker.calls) == 3
    assert result.capture == frame(1).capture
    assert result.boxes[0].identity.identity_id is None
    assert result.boxes[0].confidence is None
    assert len(evidence) == 1 and evidence[0].mask_p10 == 0.9
    assert evidence[0].image is result.image and not result.image.flags.writeable
    assert evidence[0].captured_at == result.date
    assert evidence[0].target == control.state.target(evidence[0].target.instance_id)
    assert reviews == []
    owner.request_review()
    assert send(camera, 1.5) == {}
    send(camera, 2)
    assert len(reviews) == 1
    assert reviews[0][0].review.capture == frame(2).capture
    assert reviews[0][0].review.jpeg.startswith(b"\xff\xd8")
    send(camera, 2.5)
    send(camera, 3)
    assert len(reviews) == 1  # No per-frame photo churn.


def test_anonymous_startup_catches_up_without_publishing_retained_evidence(camera):
    owner, _, _, raw, tracker, evidence, reviews, _, starts = camera
    send(camera, 0)
    owner.request_review()
    assert send(camera, 0.5, 1) == {}
    assert send(camera, 1.5, 2) == {}
    assert not evidence and not reviews
    assert len(starts) == 1 and len(tracker.calls) == 5
    assert send(camera, 2.5) == {}
    result = send(camera, 3)[SOURCE][0]
    assert len(evidence) == 1 and evidence[0].capture == result.capture
    assert len(reviews) == 1 and len(raw.calls) == 4


def test_halfstep_holds_confirmation_until_current_analyzed_evidence(camera):
    owner, control, _, _, _, evidence, reviews, *_ = camera
    ready(camera)
    owner.request_review()
    send(camera, 1.5)
    send(camera, 2)
    photo = reviews[0][0].review
    control.submit(
        ConfirmLiveIdentity.model_validate(
            {
                "version": 1,
                "command": "confirm_identity",
                "request_id": "d" * 32,
                "run_id": control.run_id,
                "source_key": control.source_key,
                "epoch": EPOCH,
                "snapshot_id": photo.snapshot_id,
                "identity_id": COW,
                "catalog_revision": 0,
            }
        )
    )
    assert send(camera, 2.5) == {}
    owner.maintain()
    assert control.state.identity(photo.target.instance_id) is None
    result = send(camera, 3)[SOURCE][0]
    assert result.boxes[0].identity.identity_id == COW
    assert result.boxes[0].identity.similarity is None
    assert evidence[-1].target.revision > photo.target.revision


@pytest.mark.parametrize("at", ["raw", "jpeg", "queued"])
def test_same_epoch_old_result_cannot_publish_after_processing_delay(
    camera, monkeypatch, at
):
    owner, control, clock, raw, _, evidence, reviews, *_ = camera
    ready(camera)
    old = evidence[-1].target
    send(camera, 1.5)
    if at == "queued":
        clock.now = 13
        result = owner.detect({SOURCE: (frame(2),)})
    else:

        def delayed(*_):
            clock.now += 1.1
            return b"old JPEG"

        if at == "raw":
            raw.hook = delayed
        else:
            owner.request_review()
            monkeypatch.setattr(continuous_identity, "encode_jpeg", delayed)
        result = send(camera, 2)
    assert result == {} and len(evidence) == 1 and not reviews
    assert control.state.target(old.instance_id) is None


@pytest.mark.parametrize("reason", ["backlog", "gap", "geometry", "epoch"])
def test_discontinuity_forgets_names_and_never_reuses_instance(camera, reason):
    owner, control, _, _, _, evidence, *_ = camera
    ready(camera)
    old = evidence[-1].target
    assert control.state.confirm(old, "cow-id", "Bella").status == "confirmed"
    if reason == "backlog":
        assert send(camera, 1.5, 2) == {}
        next_second, kwargs = 2.5, {}
    elif reason == "gap":
        assert send(camera, 2) == {}
        next_second, kwargs = 2.5, {}
    elif reason == "geometry":
        kwargs = {"shape": (22, 32, 3)}
        assert send(camera, 1.5, **kwargs) == {}
        next_second = 2
    else:
        kwargs = {"epoch": "b" * 32}
        owner.source_changed(kwargs["epoch"])
        assert send(camera, 1.5, **kwargs) == {}
        next_second = 2
    assert control.state.target(old.instance_id) is None
    send(camera, next_second, **kwargs)
    result = send(camera, next_second + 0.5, **kwargs)[SOURCE][0]
    assert result.boxes[0].identity.identity_id is None
    assert evidence[-1].target.instance_id != old.instance_id
    assert evidence[-1].target.generation > old.generation


def test_subperiod_jitter_is_operationally_tolerated_but_old_frames_are_not(camera):
    *_, starts = camera
    send(camera, 0)
    send(camera, 0.51)
    result = send(camera, 1.04)[SOURCE][0]
    assert result.capture == frame(1.04).capture
    assert len(starts) == 1
    assert send(camera, 1.04) == {}
    assert send(camera, 1.55) == {}
    assert len(starts) == 2


@pytest.mark.parametrize("at", ["raw", "tracker"])
def test_disconnect_during_inference_never_publishes_or_registers_old_pixels(
    camera, at
):
    owner, control, _, raw, tracker, evidence, reviews, *_ = camera
    ready(camera)
    old = evidence[-1].target
    boundary = raw if at == "raw" else tracker
    boundary.hook = lambda: owner.source_changed(None)
    owner.request_review()
    send(camera, 1.5) if at == "raw" else None
    assert send(camera, 2 if at == "raw" else 1.5) == {}
    assert len(evidence) == 1 and not reviews
    assert control.state.target(old.instance_id) is None


def test_idle_timeout_clears_same_epoch_before_commands_can_use_old_evidence(camera):
    owner, control, clock, _, _, evidence, *_ = camera
    ready(camera)
    old = evidence[-1].target
    clock.now = 12
    owner.maintain()
    assert control.source_is_current(EPOCH)
    assert control.state.target(old.instance_id) is None


def test_disconnect_while_encoding_requested_review_never_delivers_photo(
    camera, monkeypatch
):
    owner, control, _, _, _, evidence, reviews, statuses, _ = camera
    ready(camera)
    old = evidence[-1].target

    def interrupted_encode(image):
        owner.source_changed(None)
        return b"old camera JPEG"

    monkeypatch.setattr(continuous_identity, "encode_jpeg", interrupted_encode)
    owner.request_review()
    send(camera, 1.5)
    assert send(camera, 2) == {}
    assert not reviews and len(evidence) == 1
    assert control.state.target(old.instance_id) is None
    assert statuses[-1].kind == "identity_collecting"


def test_capture_can_supersede_final_review_publication_without_worker_failure(
    camera, monkeypatch
):
    owner, control, _, _, _, _, reviews, *_ = camera
    ready(camera)
    original = control.publish_review

    def superseded(instance, capture, jpeg):
        owner.source_changed(None)
        return original(instance, capture, jpeg)

    monkeypatch.setattr(control, "publish_review", superseded)
    owner.request_review()
    send(camera, 1.5)
    assert send(camera, 2) == {}
    assert not reviews


def test_initial_queue_saturation_and_bounded_catchup_restart_visibly(camera):
    *_, statuses, starts = camera
    send(camera, 0)
    send(camera, 0.5, 1, 1.5, 2)
    assert len(starts) == 2
    assert any("queue filled" in status.message for status in statuses)
    for start in (2.5, 4, 5.5):
        send(camera, start, start + 0.5, start + 1)
    assert len(starts) == 3
    assert any("could not catch up" in status.message for status in statuses)
    assert not camera[5]


def test_capacity_has_no_silent_selection_and_close_is_final(camera):
    owner, _, _, raw, tracker, evidence, _, statuses, _ = camera
    raw.boxes = tuple(BoundingBox(1, 1, 9, 9, "cow", 0.8) for _ in range(9))
    assert send(camera, 0) == {}
    assert not tracker.calls and not evidence
    assert "at most eight" in statuses[-1].message
    owner.close()
    owner.close()
    with pytest.raises(RuntimeError, match="closed"):
        send(camera, 0.5)


def test_other_detected_classes_cannot_seed_or_corroborate_target_tracks(camera):
    _, _, _, raw, tracker, evidence, *_ = camera
    raw.boxes = (*raw.boxes, BoundingBox(15, 1, 23, 9, "person", 0.99))
    observation = ready(camera)
    assert tracker.calls[0][1] == (1,)
    assert len(observation.boxes) == 1 and len(evidence) == 1
    assert observation.confidence == {"cow": 0.8}
    # A person over the existing cow's geometry is not corroborating cow evidence.
    raw.boxes = (BoundingBox(1, 1, 9, 9, "person", 0.99),)
    send(camera, 1.5)
    observation = send(camera, 2)[SOURCE][0]
    assert observation.boxes[0].identity.identity_id is None
    assert observation.confidence == {}
    assert len(evidence) == 1
    raw.boxes = (BoundingBox(1, 1, 9, 9, "cow", 0.8),)
    send(camera, 2.5)
    send(camera, 3)
    assert [row.analysis_index for row in evidence] == [1, 3]
