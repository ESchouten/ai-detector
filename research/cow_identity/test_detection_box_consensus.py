"""A geometric corroborator cannot assign its box to two named animal slots."""

from copy import deepcopy

from detection_box_consensus import correspondences, prepare_conditions


def box(x1, x2, track_id=0):
    return {"x1": x1, "y1": 0, "x2": x2, "y2": 10, "track_id": track_id}


def test_reciprocal_confirmation_rejects_competing_slots():
    confirmed, reciprocal = correspondences(
        [box(0, 10), box(1, 11, 1)], [box(0, 10)], 0.5
    )
    assert confirmed == {0: 0, 1: 0}
    assert reciprocal == {0: 0}
    assert correspondences([box(0, 10)], [], 0.5) == ({}, {})


def test_consensus_changes_only_paired_geometry_preserving_identity_and_inputs():
    value = {"timeline": [{"second": 0, "boxes": [box(0, 10, 4), box(50, 60, 7)]}]}
    other = {"timeline": [{"second": 0, "boxes": [box(2, 12)]}]}
    original = deepcopy(value)
    timelines, accepted = prepare_conditions(value, other, 0.5)
    assert timelines["baseline"] == value["timeline"]
    assert timelines["reciprocal_mean"][0]["boxes"] == [box(1, 11, 4), box(50, 60, 7)]
    assert accepted == {name: {0: {4}} for name in timelines}
    assert value == original
