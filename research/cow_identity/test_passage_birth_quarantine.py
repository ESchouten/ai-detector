"""Anonymous birth preserves the real quarantine's history and 1 Hz clock."""

import json
from pathlib import Path

import numpy as np
from detection_quarantine_recovery import CorroboratedRecovery
from passage_entry_births import register_anonymous_objects
from passage_entry_control import OneHertzQuarantine


def test_half_second_birth_preserves_history_and_can_receive_a_later_conflict():
    directory = Path(__file__).parent
    rules = json.loads(
        (directory / "detection_cutie_quarantine_v2_protocol.json").read_text()
    )
    recovery = json.loads(
        (directory / "detection_quarantine_recovery_protocol.json").read_text()
    )["recovery"]
    tracker = CorroboratedRecovery(rules, [1], recovery)
    clock = OneHertzQuarantine(tracker)
    original = np.zeros((8, 14), dtype=np.int64)
    original[2:5, 2:5] = 1
    for half_second in range(59):
        assert (
            clock.observe_evidence(half_second / 2, original, {1: 0.9}, [], []) == set()
        )
    history = tuple(tracker.history)
    assert len(history) == rules["history_frames"] == 30

    register_anonymous_objects(tracker, [42])
    both = original.copy()
    both[2:5, 10:13] = 42
    assert clock.observe_evidence(29.5, both, {1: 0.9, 42: 0.95}, [], []) == set()
    assert tuple(map(id, tracker.history)) == tuple(map(id, history))
    for row in history:
        assert row.areas == {1: 9, 42: 0}
        assert row.probabilities == {1: 0.9, 42: 0.0}
        np.testing.assert_array_equal(row.mask, original)

    # No reset and no second half-frame history entry: first new-object evidence
    # enters at the next integer second, using the original 30-frame policy.
    assert clock.observe_evidence(30, both, {1: 0.9, 42: 0.95}, [], []) == set()
    assert clock.observe_evidence(30.5, both, {1: 0.9, 42: 0.95}, [], []) == set()
    assert tracker.history[-1].areas == {1: 9, 42: 9}
    absorbed = both.copy()
    absorbed[absorbed == 1] = 42
    assert clock.observe_evidence(31, absorbed, {42: 0.95}, [], []) == {1, 42}
    assert set(tracker.conflicts) == {(1, 42)}
    assert tracker.events[-1]["pair"] == [1, 42]
    assert tracker.events[-1]["anchor_second"] == 30
    assert len(tracker.history) == 30
