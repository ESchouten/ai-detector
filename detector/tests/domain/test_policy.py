from datetime import datetime, timedelta

import numpy as np
import pytest

from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Observation,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, confidence_matches

START = datetime(2026, 1, 1)
IMAGE = np.zeros((8, 8, 3), dtype=np.uint8)


def observation(second: float, **scores: float) -> Observation:
    return Observation(START + timedelta(seconds=second), IMAGE, scores)


def result(event: DetectionEvent, status: ValidationStatus) -> EventResult:
    return EventResult(event, ValidationResult(status), id="a" * 32)


def test_default_cooldown_allows_an_immediate_repeat():
    cooldown = Cooldown()
    event = DetectionEvent("camera", (observation(0, cow=0.9),))
    cooldown.record(result(event, ValidationStatus.APPROVED))

    assert cooldown.allows(event)


@pytest.mark.parametrize("seconds", [3600, {"cow": 3600}])
def test_unscored_events_have_no_class_cooldown(seconds):
    cooldown = Cooldown(seconds)
    event = DetectionEvent("camera", (observation(0),))
    cooldown.record(result(event, ValidationStatus.UNVALIDATED))

    assert cooldown.allows(event)


def test_cooldown_uses_source_and_class_with_inclusive_boundary():
    cooldown = Cooldown({"cow": 10, "horse": 2})
    first = DetectionEvent("one", (observation(0, cow=0.8),))
    assert cooldown.allows(first)
    cooldown.record(result(first, ValidationStatus.APPROVED))
    assert not cooldown.allows(DetectionEvent("one", (observation(9, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("one", (observation(10, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("two", (observation(1, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("one", (observation(1, horse=0.8),)))


def test_unspecified_cooldown_class_is_unrestricted():
    cooldown = Cooldown({"cow": 10})
    event = DetectionEvent("one", (observation(0, horse=0.8),))
    cooldown.record(result(event, ValidationStatus.APPROVED))
    assert cooldown.allows(event)


@pytest.mark.parametrize(
    "status, consumes_cooldown",
    [
        (ValidationStatus.APPROVED, True),
        (ValidationStatus.UNVALIDATED, True),
        (ValidationStatus.REJECTED, False),
        (ValidationStatus.FAILED, False),
    ],
)
def test_cooldown_uses_validation_outcome(status, consumes_cooldown):
    cooldown = Cooldown(10)
    first = DetectionEvent("camera", (observation(0, cow=0.9),))

    cooldown.record(result(first, status))

    repeated = DetectionEvent("camera", (observation(1, cow=0.9),))
    assert cooldown.allows(repeated) is not consumes_cooldown
    assert cooldown.allows(DetectionEvent("camera", (observation(10, cow=0.9),)))


@pytest.mark.parametrize("status", [ValidationStatus.REJECTED, ValidationStatus.FAILED])
def test_unsuccessful_validation_preserves_the_previous_cooldown(status):
    cooldown = Cooldown(10)
    accepted = DetectionEvent("camera", (observation(0, cow=0.9),))
    unsuccessful = DetectionEvent("camera", (observation(5, cow=0.9),))

    cooldown.record(result(accepted, ValidationStatus.APPROVED))
    cooldown.record(result(unsuccessful, status))

    assert not cooldown.allows(DetectionEvent("camera", (observation(9, cow=0.9),)))
    assert cooldown.allows(DetectionEvent("camera", (observation(10, cow=0.9),)))


@pytest.mark.parametrize(
    "legs_frames, allowed", [(0, False), (1, False), (9, False), (10, True)]
)
def test_frames_inside_calf_cooldown_cannot_qualify_a_new_legs_event(
    legs_frames, allowed
):
    cooldown = Cooldown({"calf": 43200, "legs": 1800}, min_frames=10)
    first = DetectionEvent(
        "camera", tuple(observation(i, calf=0.91, legs=0.7) for i in range(10))
    )
    cooldown.record(result(first, ValidationStatus.UNVALIDATED))
    repeated = DetectionEvent(
        "camera",
        tuple(
            observation(
                1900 + i, calf=0.91, **({"legs": 0.7} if i < legs_frames else {})
            )
            for i in range(36)
        ),
    )

    assert cooldown.allows(repeated) is allowed


def test_minimum_counts_eligible_images_once_and_does_not_count_context():
    cooldown = Cooldown(min_frames=2)
    too_short = DetectionEvent(
        "camera", (observation(0), observation(1, cow=0.9, horse=0.8), observation(2))
    )
    enough = DetectionEvent(
        "camera", (observation(0, cow=0.9), observation(1, horse=0.8))
    )

    assert not cooldown.allows(too_short)
    assert cooldown.allows(enough)


def test_cooldown_expiring_during_an_event_counts_only_images_after_expiry():
    cooldown = Cooldown(10, min_frames=2)
    first = DetectionEvent("camera", (observation(0, cow=0.9), observation(1, cow=0.8)))
    cooldown.record(result(first, ValidationStatus.APPROVED))
    before_expiry = observation(9, cow=0.99)
    at_expiry = observation(10, cow=0.8)
    after_expiry = observation(11, cow=0.9)
    assert not cooldown.allows(DetectionEvent("camera", (before_expiry, at_expiry)))
    crossing = DetectionEvent("camera", (before_expiry, at_expiry, after_expiry))
    assert cooldown.allows(crossing)
    cooldown.record(result(crossing, ValidationStatus.APPROVED))

    assert not cooldown.allows(
        DetectionEvent("camera", (observation(20, cow=0.9), observation(21, cow=0.8)))
    )
    assert cooldown.allows(
        DetectionEvent("camera", (observation(21, cow=0.9), observation(22, cow=0.8)))
    )


def test_new_class_can_qualify_outside_the_best_image_without_resetting_a_blocked_class():
    cooldown = Cooldown({"calf": 10, "legs": 20}, min_frames=2)
    first = DetectionEvent(
        "camera", (observation(0, calf=0.9), observation(1, calf=0.8))
    )
    cooldown.record(result(first, ValidationStatus.UNVALIDATED))
    mixed = DetectionEvent(
        "camera",
        (observation(5, calf=0.99), observation(6, legs=0.8), observation(7, legs=0.7)),
    )
    assert cooldown.allows(mixed)
    cooldown.record(result(mixed, ValidationStatus.UNVALIDATED))

    assert mixed.best.confidence == {"calf": 0.99}
    assert not cooldown.allows(
        DetectionEvent("camera", (observation(8, legs=0.8), observation(9, legs=0.7)))
    )
    assert cooldown.allows(
        DetectionEvent("camera", (observation(10, calf=0.9), observation(11, calf=0.8)))
    )
    assert not cooldown.allows(
        DetectionEvent("camera", (observation(25, legs=0.8), observation(26, legs=0.7)))
    )
    assert cooldown.allows(
        DetectionEvent("camera", (observation(26, legs=0.8), observation(27, legs=0.7)))
    )


def test_unscored_snapshots_bypass_the_frame_minimum():
    cooldown = Cooldown(3600, min_frames=10)
    snapshot = DetectionEvent("camera", (observation(0),))
    cooldown.record(result(snapshot, ValidationStatus.UNVALIDATED))

    assert cooldown.allows(snapshot)


def test_confidence_thresholds_include_equality_and_support_no_model():
    assert confidence_matches({}, None)
    assert confidence_matches({}, 0)
    assert not confidence_matches({}, 0.1)
    assert confidence_matches({"cow": 0.8, "horse": 0.3}, {"cow": 0.8})
    assert not confidence_matches({"cow": 0.8}, {"horse": 0.5})
