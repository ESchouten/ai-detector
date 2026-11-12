import numpy as np
import pytest

from aidetector.adapters.individuals.scoring import (
    Gallery,
    NamedSighting,
    decide_together,
    self_set_threshold,
    threshold_for,
)


def unit(*values):
    vector = np.asarray(values, np.float32)
    return vector / np.linalg.norm(vector)


def sighting(name, day, *vectors):
    return NamedSighting(name, f"2026-10-{day:02d}", np.stack(vectors))


def test_a_sighting_scores_highest_for_the_individual_with_the_nearest_pictures():
    gallery = Gallery.of(
        [
            sighting("412", 1, unit(1, 0, 0), unit(0.9, 0.1, 0)),
            sighting("233", 1, unit(0, 1, 0)),
        ]
    )
    scores = gallery.scores(np.stack([unit(1, 0.05, 0)]))
    assert gallery.names == ("233", "412")
    assert scores.argmax() == 1


def test_a_close_runner_up_lowers_the_best_score():
    alone = Gallery.of(
        [sighting("412", 1, unit(1, 0, 0)), sighting("9", 1, unit(0, 0, 1))]
    )
    look_alike = Gallery.of(
        [sighting("412", 1, unit(1, 0, 0)), sighting("9", 1, unit(1, 0.2, 0))]
    )
    query = np.stack([unit(1, 0.05, 0)])
    assert look_alike.scores(query).max() < alone.scores(query).max()


def test_an_individual_is_recognised_once_among_sightings_seen_together():
    # Similarities to 233, 412 and 87; the first two are seen together.
    rows = [
        np.asarray([0.2, 0.9, 0.1], np.float32),
        np.asarray([0.6, 0.7, 0.1], np.float32),
        np.asarray([0.6, 0.7, 0.1], np.float32),
    ]
    beside = [{1}, {0}, set()]

    surest, beside_it, alone = decide_together(rows, beside, [None] * 3, 0.3)

    assert surest.recognised and surest.scores.argmax() == 1
    # 412 stands beside it, so 233 is left without a close runner-up.
    assert beside_it.recognised and beside_it.scores.argmax() == 0
    assert beside_it.scores[1] == -np.inf
    # Alone, 412 and 233 are too close to call.
    assert not alone.recognised and alone.scores.argmax() == 1


def test_a_name_a_person_gave_stands_and_is_decided_first():
    rows = [
        np.asarray([0.2, 0.9], np.float32),
        np.asarray([0.1, 0.5], np.float32),
    ]

    sure, named = decide_together(rows, [{1}, {0}], [None, 1], 0.3)

    assert named.recognised and named.scores.argmax() == 1
    # The one a person named 412 stands beside it: it can't be 412 too.
    assert not sure.recognised and sure.scores[1] == -np.inf


def test_threshold_is_the_lowest_score_whose_names_are_right_often_enough():
    scores = np.asarray([0.9, 0.8, 0.7, 0.6], np.float32)
    correct = np.asarray([True, True, False, True])
    assert threshold_for(scores, correct, 0.99) == pytest.approx(0.8)
    assert threshold_for(scores, correct, 0.7) == pytest.approx(0.6)
    assert threshold_for(scores, np.zeros(4, bool), 0.99) is None


def herd(days):
    colours = {"412": (1, 0, 0), "233": (0, 1, 0), "87": (0, 0, 1), "15": (1, 1, 0)}
    rng = np.random.default_rng(0)
    return [
        sighting(
            name,
            day,
            *(unit(*(np.asarray(colour) + rng.normal(0, 0.05, 3))) for _ in range(3)),
        )
        for day in days
        for name, colour in colours.items()
    ]


def test_the_threshold_needs_named_sightings_from_two_days():
    assert self_set_threshold(herd([1]), 0.99) is None
    threshold = self_set_threshold(herd([1, 2]), 0.99)
    assert threshold is not None
    # Withheld individuals stand in for strangers: a stranger's best score,
    # against the other individuals only, stays below the threshold.
    others = Gallery.of([s for s in herd([1, 2]) if s.name != "412"])
    assert others.scores(herd([3])[0].vectors).max() < threshold
