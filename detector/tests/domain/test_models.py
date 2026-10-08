from datetime import datetime

import pytest

from aidetector.domain.models import (
    BoundingBox,
    DetectionEvent,
    EventResult,
    IdentityMatch,
    Observation,
    ValidationResult,
    ValidationStatus,
)


@pytest.mark.parametrize(
    "boxes, expected",
    [
        ((), None),
        ((BoundingBox(10, 20, 30, 40, "cow", 0.9),), BoundingBox(10, 20, 30, 40)),
        (
            (
                BoundingBox(10, 20, 30, 40, "cow", 0.9),
                BoundingBox(50, 5, 80, 70, "horse", 0.8),
                BoundingBox(-5, 30, 12, 60),
            ),
            BoundingBox(-5, 5, 80, 70),
        ),
    ],
)
def test_enclosing_region_covers_every_box_without_a_class_label(boxes, expected):
    assert BoundingBox.enclosing(boxes) == expected


def test_a_results_individuals_are_its_own_boxes_then_what_another_rule_saw():
    bella, daisy = IdentityMatch("cow-1", "Bella", 0.9), IdentityMatch("cow-2", "Daisy")
    observation = Observation(
        datetime(2026, 1, 1),
        None,
        {"cow": 0.9},
        (
            BoundingBox(0, 0, 4, 4, "cow", 0.9, 1, bella),
            BoundingBox(4, 0, 8, 4, "cow", 0.9, 2, IdentityMatch(similarity=0.3)),
            BoundingBox(8, 0, 12, 4, "cow", 0.9, 3),
        ),
    )
    result = EventResult(
        DetectionEvent("camera", (observation,)),
        ValidationResult(ValidationStatus.UNVALIDATED),
        "a" * 32,
        seen=(daisy, IdentityMatch("cow-1", "Bella")),
    )

    assert result.identities == (bella, daisy)
