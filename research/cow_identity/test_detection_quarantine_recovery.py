"""Recovery requires distinct current detector evidence, without old pixel locations."""

import json
from pathlib import Path

import numpy as np
from detection_cutie import boxes_from_mask
from detection_cutie_quarantine import Conflict
from detection_quarantine_recovery import CorroboratedRecovery


def setup():
    rules = json.loads(
        Path(__file__)
        .with_name("detection_cutie_quarantine_v2_protocol.json")
        .read_text()
    )
    tracker = CorroboratedRecovery(
        rules,
        (1, 2),
        {
            "minimum_iou": 0.5,
            "minimum_p10": 0.7,
            "donor_area_ratio": 0.5,
            "consecutive_frames": 3,
        },
    )
    old = np.zeros((12, 12), dtype=np.uint8)
    old[:4, :4] = 1
    tracker.conflicts[(1, 2)] = Conflict(1, 2, 16, old == 1)
    moved = np.zeros_like(old)
    moved[8:12, :4] = 1
    moved[8:12, 8:12] = 2
    return tracker, moved


def observed(tracker, second, mask, probabilities=None, proposals=None):
    boxes = boxes_from_mask(mask)
    return tracker.observe_evidence(
        second,
        mask,
        probabilities or {1: 0.9, 2: 0.9},
        boxes,
        boxes if proposals is None else proposals,
    )


def test_recovery_can_follow_two_animals_away_from_the_stale_anchor():
    tracker, moved = setup()
    original = moved.copy()
    assert observed(tracker, 0, moved) == {1, 2}
    assert observed(tracker, 1, moved) == {1, 2}
    assert observed(tracker, 2, moved) == set()
    np.testing.assert_array_equal(moved, original)
    assert tracker.events == [{"second": 2, "kind": "restored", "pair": [1, 2]}]


def test_ambiguous_shared_proposal_or_low_confidence_resets_recovery_streak():
    tracker, moved = setup()
    observed(tracker, 0, moved)
    observed(tracker, 1, moved)
    # A proposal covering both slots cannot count as two independent animals.
    shared = [{"x1": 0, "y1": 8, "x2": 12, "y2": 12}]
    assert observed(tracker, 2, moved, proposals=shared) == {1, 2}
    observed(tracker, 3, moved)
    observed(tracker, 4, moved)
    assert observed(tracker, 5, moved, probabilities={1: 0.69, 2: 0.9}) == {1, 2}
    observed(tracker, 6, moved)
    observed(tracker, 7, moved)
    assert observed(tracker, 8, moved) == set()


def test_tiny_donor_cannot_recover_even_with_a_distinct_matching_proposal():
    tracker, moved = setup()
    moved[10:, :4] = 0
    moved[9, 0] = 0
    assert (moved == 1).sum() == 7
    for second in range(5):
        assert observed(tracker, second, moved) == {1, 2}
    moved[9, 0] = 1
    for second in (5, 6):
        assert observed(tracker, second, moved) == {1, 2}
    assert observed(tracker, 7, moved) == set()
