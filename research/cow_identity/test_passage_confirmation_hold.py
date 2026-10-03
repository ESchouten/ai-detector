from dataclasses import replace

from passage_confirmation_hold import ConfirmationHold
from test_passage_continuity import KNOWN, OTHER, UNKNOWN, observed

from aidetector.domain.identity import TrackAgreement


class MatcherState:
    def __init__(self):
        self._tracks = {}
        self.agreement = TrackAgreement()


def whole(observation):
    return replace(
        observation,
        boxes=tuple(
            replace(box, label="whole_visible_cow") for box in observation.boxes
        ),
    )


def test_weak_evidence_does_not_refresh_five_second_confirmation_age():
    hold = ConfirmationHold()
    state = MatcherState()
    first = observed(0, ((1, KNOWN),))
    hold.before_observation(state, "source", whole(first))
    hold.apply(first, [1], [KNOWN])
    for index in range(1, 27):
        observation = observed(index / 5)
        hold.before_observation(state, "source", whole(observation))
        result = hold.apply(observation, [1], [UNKNOWN])
        assert result.boxes[0].identity == (KNOWN if index <= 25 else UNKNOWN)


def test_strong_pending_contradiction_immediately_clears_old_identity():
    hold = ConfirmationHold()
    hold.apply(observed(0, ((1, KNOWN),)), [1], [KNOWN])
    assert hold.apply(observed(0.2), [1], [OTHER]).boxes[0].identity == UNKNOWN
    assert hold.apply(observed(0.4), [1], [UNKNOWN]).boxes[0].identity == UNKNOWN


def test_spatial_jump_and_short_gap_clear_actual_matcher_history_not_only_hold():
    for mode in ("jump", "gap", "backwards"):
        hold = ConfirmationHold()
        state = MatcherState()
        first = whole(observed(0, ((1, KNOWN),)))
        hold.before_observation(state, "source", first)
        hold.apply(first, [1], [KNOWN])
        for index in range(3):
            state.agreement.update("source", 1, observed(index / 5).date, KNOWN)
        state._tracks[("source", 1)] = object()
        second = whole(
            observed(0.2 if mode == "jump" else 0.8 if mode == "gap" else -0.2)
        )
        if mode == "jump":
            second = replace(second, boxes=(replace(second.boxes[0], x1=250, x2=330),))
        hold.before_observation(state, "source", second)
        assert ("source", 1) not in state._tracks
        assert ("source", 1) not in state.agreement._tracks
        assert hold.apply(second, [1], [UNKNOWN]).boxes[0].identity == UNKNOWN


def test_pending_other_track_competes_with_held_name_during_weak_evidence():
    hold = ConfirmationHold()
    hold.apply(observed(0, ((1, KNOWN),)), [1], [KNOWN])
    result = hold.apply(
        observed(0.2, ((1, UNKNOWN), (2, UNKNOWN))), [1, 1], [UNKNOWN, KNOWN]
    )
    assert all(box.identity == UNKNOWN for box in result.boxes)
    assert hold.apply(observed(0.4), [1], [UNKNOWN]).boxes[0].identity == UNKNOWN
