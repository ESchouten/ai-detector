from datetime import datetime, timedelta

import numpy as np
import pytest

from aidetector.domain.events import EventAssembler
from aidetector.domain.models import (
    Observation,
)
from aidetector.domain.policy import EventPolicy

START = datetime(2026, 1, 1)
IMAGE = np.zeros((8, 8, 3), dtype=np.uint8)


def observation(second: float, **scores: float) -> Observation:
    return Observation(START + timedelta(seconds=second), IMAGE, scores)


def test_event_keeps_context_but_only_counts_matching_observations():
    events = EventAssembler(EventPolicy(min_frames=2))
    assert events.observe("camera", (observation(0), observation(1, cow=0.8))) == []
    assert events.observe("camera", (observation(2, cow=0.9),)) == []
    [event] = events.finish()
    assert event.source == "camera"
    assert [item.date for item in event.observations] == [
        START + timedelta(seconds=second) for second in (0, 1, 2)
    ]
    assert event.best.confidence == {"cow": 0.9}
    assert event.duration == 2
    assert events.finish() == []


def test_context_frames_do_not_satisfy_minimum():
    events = EventAssembler(EventPolicy(min_frames=2))
    events.observe("camera", (observation(0), observation(1, cow=0.8)))
    assert events.finish() == []


def test_timeout_uses_last_matching_frame_and_expires_at_boundary():
    events = EventAssembler(EventPolicy(min_frames=1, inactivity_timeout=5))
    events.observe("camera", (observation(0, cow=0.8),))
    events.observe("camera", (observation(1),))
    assert events.advance(START + timedelta(seconds=4.999)) == []
    [event] = events.advance(START + timedelta(seconds=5))
    assert event.end == START + timedelta(seconds=1)


def test_subsecond_timeout_is_active_and_expires_at_its_boundary():
    events = EventAssembler(EventPolicy(min_frames=1, inactivity_timeout=0.5))
    events.observe("camera", (observation(0, cow=0.8),))

    assert events.advance(START + timedelta(seconds=0.499)) == []
    [event] = events.advance(START + timedelta(seconds=0.5))

    assert event.source == "camera"
    assert event.start == event.end == START


def test_trailing_frames_stop_at_configured_duration():
    events = EventAssembler(EventPolicy(min_frames=1, trailing_time=2))
    events.observe("camera", (observation(0, cow=0.8),))
    events.observe("camera", (observation(1), observation(2), observation(3)))
    [event] = events.finish()
    assert [item.date.second for item in event.observations] == [0, 1, 2]


def test_max_duration_splits_before_the_boundary_observation():
    events = EventAssembler(
        EventPolicy(min_frames=1, max_duration=3, inactivity_timeout=0)
    )
    events.observe("camera", (observation(0, cow=0.8),))
    events.observe("camera", (observation(2, cow=0.9),))
    [first] = events.observe("camera", (observation(3, cow=0.7),))
    [second] = events.finish()
    assert first.duration == 2
    assert second.start == START + timedelta(seconds=3)


@pytest.mark.parametrize("batch_sizes", [(3,), (1, 2), (2, 1), (1, 1, 1)])
def test_buffered_trailing_frames_are_saved_before_timeout(batch_sizes):
    events = EventAssembler(EventPolicy(min_frames=1))
    events.observe("camera", (observation(0, cow=0.9),))
    trailing = (observation(1), observation(2), observation(5))
    completed = []
    offset = 0
    for size in batch_sizes:
        completed.extend(events.observe("camera", trailing[offset : offset + size]))
        offset += size

    [event] = completed
    assert [item.date.second for item in event.observations] == [0, 1]
    assert events.finish() == []


@pytest.mark.parametrize("batch_sizes", [(3,), (1, 2), (2, 1), (1, 1, 1)])
def test_buffered_frames_stay_on_their_side_of_the_duration_boundary(batch_sizes):
    events = EventAssembler(
        EventPolicy(min_frames=1, max_duration=3, inactivity_timeout=0, trailing_time=2)
    )
    events.observe("camera", (observation(0, cow=0.9),))
    pending = (observation(1), observation(2), observation(3, cow=0.8))
    completed = []
    offset = 0
    for size in batch_sizes:
        completed.extend(events.observe("camera", pending[offset : offset + size]))
        offset += size
    completed.extend(events.finish())

    assert [
        [item.date.second for item in event.observations] for event in completed
    ] == [
        [0, 1, 2],
        [3],
    ]


def test_matching_observations_in_a_batch_refresh_the_inactivity_timeout():
    events = EventAssembler(EventPolicy(min_frames=3, inactivity_timeout=5))
    events.observe("camera", (observation(0, cow=0.8),))
    assert (
        events.observe("camera", (observation(4, cow=0.9), observation(8, cow=0.7)))
        == []
    )
    [event] = events.advance(START + timedelta(seconds=13))
    assert [item.date.second for item in event.observations] == [0, 4, 8]


def test_one_batch_can_contain_multiple_complete_event_windows():
    events = EventAssembler(
        EventPolicy(min_frames=2, max_duration=3, inactivity_timeout=0)
    )
    completed = events.observe(
        "camera", tuple(observation(second, cow=0.9) for second in range(7))
    )
    assert [
        [item.date.second for item in event.observations] for event in completed
    ] == [
        [0, 1, 2],
        [3, 4, 5],
    ]
    assert events.finish() == []


def test_sources_have_independent_windows():
    events = EventAssembler(EventPolicy(min_frames=1, inactivity_timeout=5))
    events.observe("one", (observation(0, cow=0.8),))
    events.observe("two", (observation(3, cow=0.9),))
    assert [event.source for event in events.advance(START + timedelta(seconds=5))] == [
        "one"
    ]
    assert [event.source for event in events.finish()] == ["two"]


def test_finishing_a_source_leaves_other_sources_open():
    events = EventAssembler(EventPolicy(min_frames=1))
    events.observe("one", (observation(0, cow=0.8),))
    events.observe("two", (observation(1, cow=0.9),))

    assert events.finish("unknown") == []
    assert [event.source for event in events.finish("one")] == ["one"]
    assert events.finish("one") == []
    assert [event.source for event in events.finish()] == ["two"]


def test_overlapping_context_does_not_duplicate_frames_or_matches():
    events = EventAssembler(EventPolicy(min_frames=3))
    events.observe("camera", (observation(0, cow=0.8), observation(1, cow=0.9)))
    events.observe("camera", (observation(1, cow=0.9), observation(2)))
    assert events.finish() == []


def test_overlapping_context_does_not_discard_later_matches_in_the_same_batch():
    events = EventAssembler(EventPolicy(min_frames=3))
    events.observe("camera", (observation(0, cow=0.8), observation(1, cow=0.9)))
    events.observe("camera", (observation(1, cow=0.9), observation(2, cow=0.8)))

    [event] = events.finish()

    assert [item.date.second for item in event.observations] == [0, 1, 2]
