from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest
from passage_torso_continuity import (
    BorderTorsoIdentifier,
    VisibleTrackHold,
    torso_presence,
)

from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation

UNKNOWN = IdentityMatch()
KNOWN = IdentityMatch("a", "Animal A", 0.8)
OTHER = IdentityMatch("b", "Animal B", 0.8)


def observed(second, tracks=((1, UNKNOWN),)):
    return Observation(
        datetime(2026, 1, 1) + timedelta(seconds=second),
        np.zeros((200, 400, 3), np.uint8),
        {},
        tuple(
            BoundingBox(
                10 + index * 100,
                10,
                90 + index * 100,
                150,
                track_id=track,
                identity=match,
            )
            for index, (track, match) in enumerate(tracks)
        ),
    )


def test_border_wrapper_preserves_exact_pixels_and_other_geometry_checks():
    image = np.arange(200 * 200 * 3, dtype=np.uint8).reshape(200, 200, 3)
    boxes = (BoundingBox(0, 20, 80, 100), BoundingBox(150, 10, 180, 40))
    observation = replace(observed(0), image=image, boxes=boxes)

    class Probe:
        def identify(self, source, received):
            height, width = received.image.shape[:2]
            assert source == "source"
            for original, shifted in zip(boxes, received.boxes, strict=True):
                np.testing.assert_array_equal(
                    image[original.y1 : original.y2, original.x1 : original.x2],
                    received.image[shifted.y1 : shifted.y2, shifted.x1 : shifted.x2],
                )
            assert usable_crop(
                received.boxes[0], received.boxes, width, height, 64, 0.2
            )
            assert not usable_crop(
                received.boxes[1], received.boxes, width, height, 64, 0.2
            )
            return replace(
                received,
                boxes=tuple(replace(box, identity=KNOWN) for box in received.boxes),
            )

    assert not usable_crop(boxes[0], boxes, 200, 200, 64, 0.2)
    result = BorderTorsoIdentifier(Probe()).identify("source", observation)
    assert result.image is image
    assert result.boxes == tuple(replace(box, identity=KNOWN) for box in boxes)


def test_hold_expires_without_refresh_and_rejects_pending_duplicate_identity():
    hold = VisibleTrackHold()
    hold.apply(observed(0, ((1, KNOWN),)), [1], [KNOWN])
    for second in (0.2, 0.8, 1.0):
        assert hold.apply(observed(second), [0], [UNKNOWN]).boxes[0].identity == KNOWN
    assert hold.apply(observed(1.2), [0], [UNKNOWN]).boxes[0].identity == UNKNOWN
    hold.apply(observed(2, ((1, KNOWN),)), [1], [KNOWN])
    conflicting = hold.apply(
        observed(2.2, ((1, UNKNOWN), (2, UNKNOWN))), [0, 1], [UNKNOWN, KNOWN]
    )
    assert all(box.identity == UNKNOWN for box in conflicting.boxes)
    assert hold.apply(observed(2.4), [0], [UNKNOWN]).boxes[0].identity == UNKNOWN


@pytest.mark.parametrize(
    "reset", ("present", "contradiction", "missing", "time", "gap", "duplicated_track")
)
def test_hold_resets_on_unsafe_continuity(reset):
    hold = VisibleTrackHold()
    hold.apply(observed(0, ((1, KNOWN),)), [1], [KNOWN])
    if reset in ("present", "contradiction"):
        result = hold.apply(
            observed(0.2), [1], [OTHER if reset == "contradiction" else UNKNOWN]
        )
    elif reset == "missing":
        hold.apply(observed(0.2, ()), [], [])
        result = hold.apply(observed(0.4), [0], [UNKNOWN])
    elif reset == "time":
        result = hold.apply(observed(0), [0], [UNKNOWN])
    elif reset == "gap":
        result = hold.apply(observed(1.2), [0], [UNKNOWN])
    else:
        result = hold.apply(
            observed(0.2, ((1, UNKNOWN), (1, UNKNOWN))), [0, 0], [UNKNOWN, UNKNOWN]
        )
    assert all(box.identity == UNKNOWN for box in result.boxes)


def test_ambiguous_partial_and_multi_parent_torsos_are_not_absent_evidence():
    first = BoundingBox(0, 0, 200, 200, label="whole_visible_cow")
    second = BoundingBox(150, 0, 350, 200, label="whole_visible_cow")
    partial = BoundingBox(180, 100, 220, 150, label="coat_torso")
    assert torso_presence((first, second, partial)) == [1, 1]
    contained_in_both = BoundingBox(160, 100, 190, 150, label="coat_torso")
    assert torso_presence((first, second, contained_in_both)) == [1, 1]
    separate = BoundingBox(400, 100, 500, 150, label="coat_torso")
    assert torso_presence((first, second, separate)) == [0, 0]


def test_serialized_arm_key_order_cannot_swap_reported_conditions():
    import json

    from passage_torso_followup import append_panels

    panels = json.loads(
        json.dumps({"border_only": [], "border_hold_1s": []}, sort_keys=True)
    )
    append_panels(panels, "opaque", ["border"], ["hold"])
    assert panels["border_only"][0]["timeline"] == ["border"]
    assert panels["border_hold_1s"][0]["timeline"] == ["hold"]
