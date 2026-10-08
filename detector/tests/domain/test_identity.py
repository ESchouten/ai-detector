from datetime import datetime, timedelta

import pytest

from aidetector.domain.identity import (
    TrackAgreement,
    choose_identity,
    reject_conflicting_matches,
)
from aidetector.domain.models import IdentityMatch

START = datetime(2026, 1, 1)
BELLA = IdentityMatch("cow-1", "Bella", 0.875)
DAISY = IdentityMatch("cow-2", "Daisy", 0.75)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "scores, similarity, margin, expected",
    [
        ((), 0.75, 0.125, IdentityMatch()),
        ((BELLA,), 0.75, 0.125, IdentityMatch(similarity=0.875)),
        ((BELLA, DAISY), 0.9, 0.125, IdentityMatch(similarity=0.875)),
        ((BELLA, DAISY), 0.75, 0.25, IdentityMatch(similarity=0.875)),
        ((DAISY, BELLA), 0.875, 0.125, BELLA),
        (
            (BELLA, IdentityMatch("cow-3", "Molly", 0.875)),
            0.75,
            0.125,
            IdentityMatch(similarity=0.875),
        ),
    ],
)
def test_gallery_decision_requires_an_impostor_absolute_score_and_margin(
    scores, similarity, margin, expected
):
    assert choose_identity(scores, similarity, margin) == expected


def test_track_needs_three_increasing_timestamps_and_duplicates_do_not_count():
    agreement = TrackAgreement()

    assert agreement.update("camera", 7, at(0), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(0), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(1), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(0.5), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(2), BELLA) == BELLA
    assert agreement.update("camera", 7, at(3), BELLA) == BELLA


@pytest.mark.parametrize("interruption", [DAISY, IdentityMatch(similarity=0.3)])
def test_different_identity_or_unknown_clears_prior_agreement(interruption):
    agreement = TrackAgreement()
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)

    assert agreement.update("camera", 7, at(3), interruption) == IdentityMatch(
        similarity=interruption.similarity
    )
    assert agreement.update("camera", 7, at(4), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(5), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(6), BELLA) == BELLA


def test_confirmed_track_keeps_its_name_while_weaker_samples_still_resemble_it():
    agreement = TrackAgreement(hold=4)
    weaker = IdentityMatch(similarity=0.5)
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)

    held = IdentityMatch("cow-1", "Bella", 0.5)
    assert agreement.update("camera", 7, at(3), weaker, "cow-1") == held
    assert agreement.update("camera", 7, at(6), weaker, "cow-1") == held
    # The hold counts from the last match, not from the last held sample.
    assert agreement.update("camera", 7, at(7), weaker, "cow-1") == weaker
    assert agreement.update("camera", 7, at(8), BELLA).identity_id is None


def test_a_match_during_the_hold_continues_the_confirmation():
    agreement = TrackAgreement(hold=4)
    weaker = IdentityMatch(similarity=0.5)
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)
    agreement.update("camera", 7, at(3), weaker, "cow-1")

    assert agreement.update("camera", 7, at(4), BELLA) == BELLA
    assert agreement.update("camera", 7, at(8), weaker, "cow-1").identity_id == "cow-1"


@pytest.mark.parametrize("resembles", [None, "cow-2"])
def test_hold_ends_when_the_sample_resembles_nobody_or_someone_else(resembles):
    agreement = TrackAgreement(hold=60)
    weaker = IdentityMatch(similarity=0.5)
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)

    assert agreement.update("camera", 7, at(3), weaker, resembles) == weaker
    assert agreement.update("camera", 7, at(4), weaker, "cow-1") == weaker


def test_holding_never_confirms_a_track_or_bridges_a_long_gap():
    agreement = TrackAgreement(hold=60)
    weaker = IdentityMatch(similarity=0.5)
    agreement.update("camera", 7, at(0), BELLA)
    agreement.update("camera", 7, at(1), BELLA)
    assert agreement.update("camera", 7, at(2), weaker, "cow-1") == weaker

    for second in range(3, 6):
        agreement.update("camera", 8, at(second), BELLA)
    assert agreement.update("camera", 8, at(11), weaker, "cow-1") == weaker


def test_missing_track_never_confirms_and_sources_and_tracks_stay_independent():
    agreement = TrackAgreement()
    for second in range(3):
        assert agreement.update("camera", None, at(second), BELLA) == IdentityMatch(
            similarity=BELLA.similarity
        )
        agreement.update("camera", 7, at(second), BELLA)

    assert agreement.update("other-camera", 7, at(3), BELLA).identity_id is None
    assert agreement.update("camera", 8, at(3), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(3), BELLA) == BELLA
    assert agreement.update("other-camera", 7, at(4), BELLA).identity_id is None
    assert agreement.update("other-camera", 7, at(5), BELLA) == BELLA


def test_gap_boundary_allows_continuity_but_long_gap_restarts_reused_track():
    agreement = TrackAgreement(max_gap=5)
    assert agreement.update("camera", 7, at(0), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(5), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(10), BELLA) == BELLA

    assert agreement.update("camera", 7, at(16), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(17), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(18), BELLA) == BELLA


def test_gallery_change_clears_confirmation():
    agreement = TrackAgreement()
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)
    agreement.clear()

    assert agreement.update("camera", 7, at(3), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(4), BELLA).identity_id is None
    assert agreement.update("camera", 7, at(5), BELLA) == BELLA


def test_camera_reset_does_not_remove_another_cameras_agreement():
    agreement = TrackAgreement()
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)
        agreement.update("other", 7, at(second), DAISY)
    agreement.clear_source("camera")

    assert agreement.update("camera", 7, at(3), BELLA).identity_id is None
    assert agreement.update("other", 7, at(3), DAISY) == DAISY


def test_stale_cleanup_only_discards_expired_tracks_for_its_source():
    agreement = TrackAgreement()
    for second in range(3):
        agreement.update("camera", 7, at(second), BELLA)
        agreement.update("other", 7, at(second), DAISY)
    agreement.update("camera", 8, at(7), BELLA)
    agreement.update("camera", 8, at(8), BELLA)
    agreement.discard_stale("camera", at(8))

    # Replayed time demonstrates that cleanup removed the expired state itself.
    assert agreement.update("camera", 7, at(3), BELLA).identity_id is None
    assert agreement.update("other", 7, at(3), DAISY) == DAISY
    assert agreement.update("camera", 8, at(9), BELLA) == BELLA


def test_simultaneous_collisions_reject_every_duplicate_without_guessing_a_winner():
    unknown = IdentityMatch(similarity=0.2)
    lower_bella = IdentityMatch("cow-1", "Bella", 0.8)

    assert reject_conflicting_matches((BELLA, DAISY, lower_bella, unknown)) == (
        IdentityMatch(similarity=0.875),
        DAISY,
        IdentityMatch(similarity=0.8),
        unknown,
    )
    assert reject_conflicting_matches((unknown, IdentityMatch())) == (
        unknown,
        IdentityMatch(),
    )
