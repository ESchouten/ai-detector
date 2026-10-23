import numpy as np
import pytest

from aidetector.adapters.individuals.scoring import (
    Gallery,
    NamedSighting,
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
