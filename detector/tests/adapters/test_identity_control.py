"""Real catalog reads and worker-owned confirmation, without a GPU or sleeps."""

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.identity_control import (
    ConfirmLiveIdentity,
    IdentityAcknowledgement,
    IdentityReview,
    LiveIdentityControl,
)
from aidetector.domain.live_identity import LiveIdentityState
from aidetector.domain.models import CaptureStamp

RUN = "1" * 32
SOURCE = "2" * 64
EPOCH = "3" * 32
COW = "4" * 32


@dataclass
class Clock:
    now: float = 10

    def __call__(self) -> float:
        return self.now


def write_catalog(directory: Path, revision: int = 1, name: str = "Bella") -> None:
    (directory / "catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "identities": [{"id": COW, "name": name, "samples": []}],
            }
        )
    )


@pytest.fixture
def camera(tmp_path):
    write_catalog(tmp_path)
    state = LiveIdentityState()
    clock = Clock()
    replies: list[IdentityAcknowledgement] = []
    control = LiveIdentityControl(
        RUN, SOURCE, state, IdentityCatalog(tmp_path), replies.append, clock=clock
    )
    control.source_changed(EPOCH)
    assert control.change_epoch(EPOCH)
    state.add("animal-a")
    review = control.publish_review(
        "animal-a", CaptureStamp(EPOCH, 100, 10), b"exact analyzed JPEG"
    )
    return control, state, clock, replies, review


def command(review: IdentityReview, **changes) -> ConfirmLiveIdentity:
    return ConfirmLiveIdentity.model_validate(
        {
            "version": 1,
            "command": "confirm_identity",
            "request_id": "5" * 32,
            "run_id": RUN,
            "source_key": SOURCE,
            "epoch": review.capture.epoch,
            "snapshot_id": review.snapshot_id,
            "identity_id": COW,
            "catalog_revision": 1,
            **changes,
        }
    )


def test_input_thread_only_queues_and_retry_has_one_effect(camera):
    control, state, _, replies, review = camera
    request = command(review)
    thread = Thread(target=control.submit, args=(request,))
    thread.start()
    thread.join()
    control.submit(request)
    assert state.identity("animal-a") is None
    assert replies == []

    control.drain({"animal-a"})
    target = state.target("animal-a")
    assert replies == [
        IdentityAcknowledgement(request.request_id, "confirmed", COW, "Bella")
    ]
    assert review.jpeg == b"exact analyzed JPEG"
    assert review.capture.sequence == 100
    assert state.identity("animal-a").evidence == "human_confirmed_continuity"
    control.submit(request)
    control.drain({"animal-a"})
    assert replies[1] == replies[0]
    assert state.target("animal-a") == target


@pytest.mark.parametrize(
    "reason", ["epoch", "retired", "continuity", "ambiguous", "expired"]
)
def test_old_photo_cannot_name_another_or_unreviewable_animal(camera, reason):
    control, state, clock, replies, review = camera
    if reason == "epoch":
        control.source_changed("6" * 32)
        assert control.change_epoch("6" * 32)
        state.add("animal-a")
    elif reason == "retired":
        state.retire("animal-a")
        state.add("animal-a")
    elif reason == "continuity":
        state.invalidate("animal-a")
    elif reason == "expired":
        clock.now += 121
    control.submit(command(review))
    control.drain(set() if reason == "ambiguous" else {"animal-a"})
    assert replies[-1].status == "stale"
    assert state.identity("animal-a") is None


def test_queue_deadline_and_shutdown_never_apply_late_confirmation(camera):
    control, state, clock, replies, review = camera
    control.submit(command(review))
    clock.now += 5
    control.drain({"animal-a"})
    assert replies[-1].status == "unavailable"
    assert state.identity("animal-a") is None
    control.submit(command(review, request_id="6" * 32))
    control.close()
    assert replies[-1].status == "unavailable"
    control.submit(command(review, request_id="7" * 32))
    assert replies[-1].status == "unavailable"
    assert state.target("animal-a") is None


def test_recovery_needs_a_fresh_photo_without_forgetting_the_confirmed_name(camera):
    control, state, _, replies, initial = camera
    control.submit(command(initial))
    control.drain({"animal-a"})
    confirmed = state.identity("animal-a")
    before_ambiguity = control.publish_review("animal-a", initial.capture, b"old")
    state.add("animal-b")
    other = control.publish_review("animal-b", initial.capture, b"unaffected")

    # A click may be queued while inference discovers ambiguity. Recovery must
    # not make that old frozen photo a valid confirmation target again.
    control.submit(command(before_ambiguity, request_id="6" * 32))
    control.invalidate_reviews({"animal-a"})
    control.drain({"animal-a", "animal-b"})
    assert replies[-1].status == "stale"
    assert state.identity("animal-a") == confirmed
    control.submit(command(other, request_id="7" * 32))
    control.drain({"animal-a", "animal-b"})
    assert replies[-1].status == "identity_in_use"

    after_recovery = control.publish_review("animal-a", initial.capture, b"fresh")
    control.submit(command(after_recovery, request_id="8" * 32))
    control.drain({"animal-a", "animal-b"})
    assert replies[-1].status == "confirmed"


def test_same_epoch_reset_rejects_pending_photo_and_preserves_retry_receipt(camera):
    control, state, _, replies, initial = camera
    request = command(initial)
    control.submit(request)
    control.drain({"animal-a"})
    old_target = state.target("animal-a")
    pending = control.publish_review("animal-a", initial.capture, b"before backlog")
    control.submit(command(pending, request_id="6" * 32))

    control.reset_tracking()
    assert replies[-1].status == "stale"
    assert control.source_is_current(EPOCH)
    new_target = state.add("animal-a")
    assert new_target.generation > old_target.generation
    assert state.identity("animal-a") is None
    control.submit(request)
    assert replies[-1].status == "confirmed"  # Receipt, not a second mutation.
    assert state.identity("animal-a") is None


def test_catalog_io_cannot_outlive_current_analyzed_evidence(tmp_path):
    write_catalog(tmp_path)
    clock = Clock()

    class DelayedCatalog(IdentityCatalog):
        def load(self):
            value = super().load()
            clock.now += 1.1
            return value

    state, replies = LiveIdentityState(), []
    control = LiveIdentityControl(
        RUN, SOURCE, state, DelayedCatalog(tmp_path), replies.append, clock=clock
    )
    control.source_changed(EPOCH)
    control.change_epoch(EPOCH)
    state.add("animal-a")
    photo = control.publish_review("animal-a", CaptureStamp(EPOCH, 10, 10), b"review")
    control.submit(command(photo))
    control.drain({"animal-a"}, evidence_deadline=11)
    assert replies[-1].status == "unavailable"
    assert state.identity("animal-a") is None


def test_name_comes_from_current_catalog_and_revision_is_checked(camera, tmp_path):
    control, state, _, replies, review = camera
    write_catalog(tmp_path, revision=2, name="Bella renamed")
    control.submit(command(review))
    control.drain({"animal-a"})
    assert replies[-1].status == "catalog_changed"
    assert state.identity("animal-a") is None
    control.submit(command(review, request_id="6" * 32, catalog_revision=2))
    control.drain({"animal-a"})
    assert replies[-1].name == "Bella renamed"


def test_duplicate_name_conflict_and_two_tabs_are_explicit(camera):
    control, state, _, replies, first = camera
    state.add("animal-b")
    second = control.publish_review("animal-b", first.capture, b"other JPEG")
    control.submit(command(first))
    control.submit(command(second, request_id="6" * 32))
    control.drain({"animal-a", "animal-b"})
    assert [reply.status for reply in replies] == ["confirmed", "identity_in_use"]
    control.submit(command(first, request_id="7" * 32))
    control.drain({"animal-a", "animal-b"})
    assert replies[-1].status == "stale"
    assert state.identity("animal-b") is None


def test_camera_run_and_bounded_queue_reject_without_changing_state(camera):
    control, state, _, replies, review = camera
    control.submit(command(review, run_id="8" * 32))
    control.submit(command(review, source_key="9" * 64))
    for i in range(17):
        control.submit(command(review, request_id=f"{i:032x}"))
    assert [reply.status for reply in replies] == ["unavailable"] * 3
    assert state.identity("animal-a") is None
    control.drain({"animal-a"})
    assert sum(reply.status == "confirmed" for reply in replies) == 1


def test_evicted_snapshot_is_stale_and_bad_catalog_is_observable(
    camera, tmp_path, caplog
):
    control, state, _, replies, old = camera
    for _ in range(32):
        recent = control.publish_review("animal-a", old.capture, b"new JPEG")
    control.submit(command(old))
    control.drain({"animal-a"})
    assert replies[-1].status == "stale"
    (tmp_path / "catalog.json").write_text("not JSON")
    control.submit(command(recent, request_id="6" * 32))
    control.drain({"animal-a"})
    assert replies[-1].status == "unavailable"
    assert "could not read the confirmed herd" in caplog.text
    assert state.identity("animal-a") is None


def test_external_command_rejects_untrusted_name_and_invalid_identifiers(camera):
    review = camera[-1]
    with pytest.raises(ValidationError):
        command(review, name="Client supplied name")
    with pytest.raises(ValidationError):
        command(review, snapshot_id="../../a")
    with pytest.raises(ValidationError):
        command(review, catalog_revision="1")


@pytest.mark.parametrize(
    ("submitted_at", "io_delay", "expected"),
    [(129.9, 1, "stale"), (10, 6, "unavailable")],
)
def test_catalog_io_cannot_extend_snapshot_or_command_deadline(
    tmp_path, submitted_at, io_delay, expected
):
    clock = Clock()

    class SlowCatalog(IdentityCatalog):
        def load(self):
            clock.now += io_delay
            return super().load()

    write_catalog(tmp_path)
    state = LiveIdentityState()
    replies = []
    control = LiveIdentityControl(
        RUN, SOURCE, state, SlowCatalog(tmp_path), replies.append, clock=clock
    )
    control.source_changed(EPOCH)
    assert control.change_epoch(EPOCH)
    state.add("animal-a")
    review = control.publish_review(
        "animal-a", CaptureStamp(EPOCH, 1, 10), b"exact JPEG"
    )
    clock.now = submitted_at
    control.submit(command(review))
    control.drain({"animal-a"})
    assert replies[-1].status == expected
    assert state.identity("animal-a") is None


def test_retry_after_receipt_eviction_cannot_apply_a_second_time(camera):
    control, state, _, replies, review = camera
    original = command(review)
    control.submit(original)
    control.drain({"animal-a"})
    confirmed_target = state.target("animal-a")
    for i in range(128):
        control.submit(command(review, request_id=f"{i:032x}"))
        control.drain({"animal-a"})
    control.submit(original)
    control.drain({"animal-a"})
    assert replies[-1].status == "stale"
    assert state.target("animal-a") == confirmed_target
    assert sum(reply.status == "confirmed" for reply in replies) == 1


@pytest.mark.parametrize("replacement_epoch", [None, "6" * 32])
def test_capture_change_during_catalog_read_rejects_old_frame(
    tmp_path, replacement_epoch
):
    reading, resume = Event(), Event()

    class PausedCatalog(IdentityCatalog):
        def load(self):
            reading.set()
            assert resume.wait(2), "Test did not release catalog I/O"
            return super().load()

    write_catalog(tmp_path)
    state = LiveIdentityState()
    replies = []
    control = LiveIdentityControl(
        RUN, SOURCE, state, PausedCatalog(tmp_path), replies.append
    )
    control.source_changed(EPOCH)
    assert control.change_epoch(EPOCH)
    state.add("animal-a")
    review = control.publish_review(
        "animal-a", CaptureStamp(EPOCH, 1, 10), b"exact JPEG"
    )
    control.submit(command(review))
    worker = Thread(target=control.drain, args=({"animal-a"},))
    worker.start()
    try:
        assert reading.wait(2), "Worker did not reach catalog I/O"
        control.source_changed(replacement_epoch)
        assert not control.source_is_current(EPOCH)
    finally:
        resume.set()
        worker.join(2)
    assert not worker.is_alive()
    assert replies[-1].status == "stale"
    assert state.identity("animal-a") is None
    assert not control.change_epoch(EPOCH)
    with pytest.raises(ValueError, match="current epoch"):
        control.publish_review("animal-a", review.capture, b"late old frame")
    if replacement_epoch is not None:
        assert control.change_epoch(replacement_epoch)
        assert state.target("animal-a") is None
