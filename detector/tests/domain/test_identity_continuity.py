import pytest

from aidetector.domain.identity_continuity import (
    ContinuityChange,
    IdentityContinuity,
    ObjectQuality,
    reciprocal_matches,
)
from aidetector.domain.models import BoundingBox

BOXES = (
    BoundingBox(0, 0, 10, 10, track_id=7),
    BoundingBox(20, 0, 30, 10, track_id=42),
)


def objects(area=100, probability=0.9):
    return (ObjectQuality(7, area, probability), ObjectQuality(42, 100, 0.9))


def no_overlap(frame, donor, receiver):
    return 0.0


def absorbed(frame, donor, receiver):
    return 0.5 if (donor, receiver) == (7, 42) else 0.0


def warmed():
    state = IdentityContinuity((7, 42))
    for second in range(30):
        state.observe(second, objects(), BOXES, BOXES, no_overlap)
    return state


def test_reciprocal_ties_are_input_ordered_and_geometry_has_no_plus_one():
    assert reciprocal_matches(BOXES, (BOXES[0], BOXES[0], BOXES[1])) == {0: 0, 1: 2}
    assert reciprocal_matches((BOXES[0], BOXES[0]), (BOXES[0],)) == {0: 0}
    assert (
        reciprocal_matches((BoundingBox(0, 0, 1, 1),), (BoundingBox(1, 0, 2, 1),)) == {}
    )
    assert reciprocal_matches(
        (BoundingBox(0, 0, 10, 10),), (BoundingBox(0, 0, 5, 10),)
    ) == {0: 0}


def test_absorption_uses_thirty_preceding_frames_and_suppresses_both_endpoints():
    state = IdentityContinuity((7, 42))
    for second in range(29):
        state.observe(second, objects(), BOXES, BOXES, no_overlap)
    assert not state.observe(29, objects(24), BOXES, BOXES, absorbed).changes
    # Equal probabilities choose the latest adequate raw-area anchor, frame28.
    result = state.observe(30, objects(24), BOXES, BOXES, absorbed)
    assert result.changes == (ContinuityChange("quarantined", 7, 42, 28),)
    assert result.conflicted_ids == frozenset((7, 42))
    assert not result.eligible_ids
    assert result.reciprocal_pairs == ((7, 0), (42, 1))


def test_highest_quality_anchor_precedes_recency_and_is_requested_without_pixels():
    state = IdentityContinuity((7, 42))
    for second in range(30):
        state.observe(
            second,
            objects(probability=0.95 if second == 3 else 0.9),
            BOXES,
            BOXES,
            no_overlap,
        )
    calls = []

    def coverage(frame, donor, receiver):
        calls.append((frame, donor, receiver))
        return 0.5

    result = state.observe(30, objects(0, None), (), (), coverage)
    assert calls == [(3, 7, 42)]
    assert result.changes == (ContinuityChange("quarantined", 7, 42, 3),)


def test_recovery_requires_three_consecutive_distinct_current_confirmations():
    state = warmed()
    state.observe(30, objects(24), BOXES, BOXES, absorbed)
    for second in (31, 32):
        assert not state.observe(
            second, objects(50, 0.7), BOXES, BOXES, no_overlap
        ).eligible_ids
    # One shared proposal cannot corroborate both objects; recovery restarts.
    state.observe(33, objects(), BOXES, BOXES[:1], no_overlap)
    for second in (34, 35):
        assert not state.observe(
            second, objects(50, 0.7), BOXES, BOXES, no_overlap
        ).eligible_ids
    result = state.observe(36, objects(50, 0.7), BOXES, BOXES, no_overlap)
    assert result.changes == (ContinuityChange("restored", 7, 42),)
    assert result.eligible_ids == frozenset((7, 42))
    assert not result.conflicted_ids


def test_zero_areas_remain_in_reference_median_and_history_evicts_old_frames():
    state = warmed()
    for second in range(30, 60):
        result = state.observe(
            second, objects(0, None), BOXES[1:], BOXES[1:], no_overlap
        )
        assert result.eligible_ids == frozenset((42,))
    calls = []

    def coverage(frame, donor, receiver):
        calls.append(frame)
        return 1.0

    assert not state.observe(60, objects(0, None), (), (), coverage).changes
    assert calls == []  # Median is zero, not the stale original100-pixel body.


def test_drop_or_repeated_evidence_is_rejected_without_advancing_state():
    state = warmed()
    for invalid in (29, 31):
        with pytest.raises(ValueError, match="consecutive"):
            state.observe(invalid, objects(), BOXES, BOXES, no_overlap)
    assert state.observe(
        30, objects(), BOXES, BOXES, no_overlap
    ).eligible_ids == frozenset((7, 42))


def test_fixed_capacity_and_unknown_objects_fail_instead_of_reusing_identity():
    for ids in ((), (7, 7), tuple(range(1, 10))):
        with pytest.raises(ValueError, match="distinct stable"):
            IdentityContinuity(ids)
    state = IdentityContinuity((7, 42))
    with pytest.raises(ValueError, match="every fixed"):
        state.observe(0, objects()[:1], BOXES, BOXES, no_overlap)
    with pytest.raises(ValueError, match="distinct stable object"):
        state.observe(
            0, objects(), (BoundingBox(0, 0, 10, 10, track_id=8),), BOXES, no_overlap
        )
    result = state.observe(0, objects(probability=0.69), BOXES, BOXES, no_overlap)
    assert result.eligible_ids == frozenset((42,))
    assert result.reciprocal_pairs == ((7, 0), (42, 1))
