from datetime import datetime, timedelta

import numpy as np

from aidetector.adapters.named_sightings import NamedSightings
from aidetector.domain.models import (
    BoundingBox,
    DetectionEvent,
    IdentityMatch,
    Observation,
)

START = datetime(2026, 1, 1)
BELLA = IdentityMatch("cow-1", "Bella", 0.9)
DAISY = IdentityMatch("cow-2", "Daisy", 0.8)


def recognised(second, *cows, size=(720, 1280)):
    """What the identity rule saw: one box per cow, on its own picture size."""
    return Observation(
        START + timedelta(seconds=second),
        np.zeros((*size, 3), dtype=np.uint8),
        {"cow": 0.9},
        tuple(
            BoundingBox(*box, "cow", 0.9, track, identity)
            for track, (identity, box) in enumerate(cows)
        ),
    )


def mount(start, end, box=(100, 100, 400, 300)):
    """A behaviour rule's event on a picture half that size."""
    moments = tuple(
        Observation(
            START + timedelta(seconds=second),
            np.zeros((360, 640, 3), dtype=np.uint8),
            {"mount": 0.9},
            (BoundingBox(*box, "mount", 0.9),),
        )
        for second in range(start, end + 1)
    )
    return DetectionEvent("barn", moments)


# Inside the mount's box once both pictures are measured in fractions.
IN_MOUNT = (240, 220, 700, 560)
ELSEWHERE = (900, 220, 1200, 560)


def test_an_event_takes_the_names_another_rule_recognised_inside_it():
    sightings = NamedSightings()
    for second in range(10, 14):
        sightings.record(
            "barn", recognised(second, (BELLA, IN_MOUNT), (DAISY, ELSEWHERE))
        )

    assert sightings.named(mount(10, 13)) == (BELLA,)


def test_names_come_only_from_the_same_camera_and_from_while_the_event_lasted():
    sightings = NamedSightings()
    for second in (26, 27, 28):
        sightings.record("barn", recognised(second, (BELLA, IN_MOUNT)))
    for second in (29, 30, 31):
        sightings.record("barn", recognised(second, (DAISY, IN_MOUNT)))
    for second in (30, 31):
        sightings.record("yard", recognised(second, (BELLA, IN_MOUNT)))

    # Bella stood there until two seconds before the mount, and is on another camera now.
    assert sightings.named(mount(30, 33)) == (DAISY,)


def test_unrecognised_boxes_are_not_kept_and_old_sightings_are_dropped():
    sightings = NamedSightings(keep=60)
    unknown = IdentityMatch(similarity=0.4)
    for second in (0, 1):
        sightings.record(
            "barn", recognised(second, (BELLA, IN_MOUNT), (unknown, IN_MOUNT))
        )
    assert sightings.named(mount(0, 1)) == (BELLA,)

    sightings.record("barn", recognised(100))

    assert sightings.named(mount(0, 1)) == ()
