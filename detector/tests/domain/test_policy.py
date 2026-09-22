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


def test_default_cooldown_allows_an_immediate_repeat():
    cooldown = Cooldown()
    event = DetectionEvent("camera", (observation(0, cow=0.9),))
    cooldown.record(EventResult(event, ValidationResult(ValidationStatus.APPROVED)))

    assert cooldown.allows(event)


@pytest.mark.parametrize("seconds", [3600, {"cow": 3600}])
def test_unscored_events_have_no_class_cooldown(seconds):
    cooldown = Cooldown(seconds)
    event = DetectionEvent("camera", (observation(0),))
    cooldown.record(EventResult(event, ValidationResult(ValidationStatus.UNVALIDATED)))

    assert cooldown.allows(event)


def test_cooldown_uses_source_and_class_with_inclusive_boundary():
    cooldown = Cooldown({"cow": 10, "horse": 2})
    first = DetectionEvent("one", (observation(0, cow=0.8),))
    assert cooldown.allows(first)
    cooldown.record(EventResult(first, ValidationResult(ValidationStatus.APPROVED)))
    assert not cooldown.allows(DetectionEvent("one", (observation(9, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("one", (observation(10, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("two", (observation(1, cow=0.8),)))
    assert cooldown.allows(DetectionEvent("one", (observation(1, horse=0.8),)))


def test_unspecified_cooldown_class_is_unrestricted():
    cooldown = Cooldown({"cow": 10})
    event = DetectionEvent("one", (observation(0, horse=0.8),))
    cooldown.record(EventResult(event, ValidationResult(ValidationStatus.APPROVED)))
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

    cooldown.record(EventResult(first, ValidationResult(status)))

    repeated = DetectionEvent("camera", (observation(1, cow=0.9),))
    assert cooldown.allows(repeated) is not consumes_cooldown
    assert cooldown.allows(DetectionEvent("camera", (observation(10, cow=0.9),)))


@pytest.mark.parametrize("status", [ValidationStatus.REJECTED, ValidationStatus.FAILED])
def test_unsuccessful_validation_preserves_the_previous_cooldown(status):
    cooldown = Cooldown(10)
    accepted = DetectionEvent("camera", (observation(0, cow=0.9),))
    unsuccessful = DetectionEvent("camera", (observation(5, cow=0.9),))

    cooldown.record(EventResult(accepted, ValidationResult(ValidationStatus.APPROVED)))
    cooldown.record(EventResult(unsuccessful, ValidationResult(status)))

    assert not cooldown.allows(DetectionEvent("camera", (observation(9, cow=0.9),)))
    assert cooldown.allows(DetectionEvent("camera", (observation(10, cow=0.9),)))


def test_confidence_thresholds_include_equality_and_support_no_model():
    assert confidence_matches({}, None)
    assert confidence_matches({}, 0)
    assert not confidence_matches({}, 0.1)
    assert confidence_matches({"cow": 0.8, "horse": 0.3}, {"cow": 0.8})
    assert not confidence_matches({"cow": 0.8}, {"horse": 0.5})
