import numpy as np

from policy import Limits, Namer

LIMITS = Limits(floor=0.6, margin=0.2, observations=2, memory=0.0)
CLEAR_A = np.array([0.9, 0.1])
CLEAR_B = np.array([0.1, 0.9])
VAGUE = np.array([0.5, 0.45])


def names(namer, seconds, *observations):
    return namer.update(seconds, list(observations))


def test_a_name_needs_repeated_agreement_of_the_same_track():
    namer = Namer(["a", "b"], LIMITS)
    assert names(namer, 0, (1, CLEAR_A)) == [None]
    assert names(namer, 1, (1, CLEAR_A)) == ["a"]


def test_weak_or_changed_evidence_withdraws_the_name():
    namer = Namer(["a", "b"], LIMITS)
    names(namer, 0, (1, CLEAR_A))
    names(namer, 1, (1, CLEAR_A))
    assert names(namer, 2, (1, VAGUE)) == [None]
    assert names(namer, 3, (1, CLEAR_B)) == [None]
    assert names(namer, 4, (1, CLEAR_B)) == ["b"]


def test_a_track_seen_again_after_a_long_gap_starts_over():
    namer = Namer(["a", "b"], LIMITS)
    names(namer, 0, (1, CLEAR_A))
    names(namer, 1, (1, CLEAR_A))
    assert names(namer, 30, (1, CLEAR_A)) == [None]


def test_one_cow_is_not_shown_on_two_animals_at_once():
    namer = Namer(["a", "b"], LIMITS)
    weaker = np.array([0.8, 0.1])
    names(namer, 0, (1, CLEAR_A), (2, weaker))
    assert names(namer, 1, (1, CLEAR_A), (2, weaker)) == ["a", None]


def test_boxes_without_a_track_are_never_named():
    namer = Namer(["a", "b"], LIMITS)
    names(namer, 0, (None, CLEAR_A))
    assert names(namer, 1, (None, CLEAR_A)) == [None]


def test_an_animal_that_looks_most_like_another_farms_cow_is_not_named():
    namer = Namer(["a", "b", None], LIMITS)
    foreign = np.array([0.2, 0.1, 0.9])
    names(namer, 0, (1, foreign))
    assert names(namer, 1, (1, foreign)) == [None]
    close = np.array([0.9, 0.1, 0.8])
    names(namer, 2, (2, close))
    assert names(namer, 3, (2, close)) == [None]


def test_a_shown_name_survives_weaker_evidence_within_its_keep_limits():
    limits = Limits(
        floor=0.8, margin=0.3, observations=2, memory=0.0, keep_floor=0.6, keep_margin=0.1
    )
    namer = Namer(["a", "b"], limits)
    weaker = np.array([0.7, 0.5])
    names(namer, 0, (1, CLEAR_A))
    assert names(namer, 1, (1, CLEAR_A)) == ["a"]
    assert names(namer, 2, (1, weaker)) == ["a"]
    # The same weaker evidence cannot start a name on another track.
    names(namer, 3, (2, weaker))
    assert names(namer, 4, (2, weaker)) == [None]


def test_an_unfit_crop_hides_the_name_without_losing_the_evidence():
    namer = Namer(["a", "b"], LIMITS)
    names(namer, 0, (1, CLEAR_A))
    assert names(namer, 1, (1, CLEAR_A)) == ["a"]
    assert names(namer, 2, (1, None)) == [None]
    assert names(namer, 3, (1, CLEAR_A)) == ["a"]


def test_a_look_alike_is_blocked_while_the_better_match_is_in_view():
    limits = Limits(floor=0.6, margin=0.2, observations=1, memory=0.0)
    namer = Namer(["a", "b"], limits)
    look_alike = np.array([0.8, 0.1])
    # The better match is too ambiguous to be shown itself, yet keeps the claim.
    ambiguous = np.array([0.85, 0.75])
    assert names(namer, 0, (1, look_alike), (2, ambiguous)) == [None, None]
    assert names(namer, 1, (1, look_alike)) == ["a"]
