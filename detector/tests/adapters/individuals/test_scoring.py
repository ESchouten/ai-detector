import numpy as np
import pytest

from aidetector.adapters.individuals.scoring import (
    Gallery,
    NamedSighting,
    decide_together,
    self_set_threshold,
    threshold_for,
    with_coat,
)


def unit(*values):
    vector = np.asarray(values, np.float32)
    return vector / np.linalg.norm(vector)


def sighting(name, day, *vectors):
    return NamedSighting(
        f"{name} on day {day}", name, f"2026-10-{day:02d}", np.stack(vectors)
    )


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


def test_later_pictures_are_compared_against_but_never_asked_with():
    seen = NamedSighting(
        "seen",
        "412",
        "2026-10-01",
        np.stack([unit(1, 0, 0)]),
        np.stack([unit(0, 1, 0)]),
    )
    other = sighting("233", 1, unit(0, 0, 1))
    gallery = Gallery.of([seen, other])
    assert len(gallery.vectors) == 3
    # Her other side is recognised through a later picture.
    assert gallery.names[gallery.scores(np.stack([unit(0, 1, 0.1)])).argmax()] == "412"

    # A sighting asks with its own pictures only, as new tracks do.
    assert len(seen.vectors) == 1


def test_a_coat_check_compares_with_the_saved_pictures_of_the_likeliest_names():
    turned = NamedSighting(
        "turned",
        "412",
        "2026-10-02",
        np.stack([unit(0.2, 1, 0)]),
        # Her later pictures look most like the sighting, but were not saved.
        np.stack([unit(1, 0, 0)]),
    )
    gallery = Gallery.of(
        [
            sighting("412", 1, unit(1, 0.4, 0), unit(1, 0.1, 0), unit(1, 0.3, 0)),
            turned,
            sighting("233", 1, unit(0.6, 0, 1)),
            sighting("87", 1, unit(0.3, 0, 1)),
            sighting("15", 1, unit(0, 0, 1)),
        ]
    )
    asked = np.stack([unit(1, 0, 0), unit(1, 0.1, 0)])

    chosen = gallery.shortlist(asked, gallery.similarities(asked))

    # The three names most like the sighting, best first, each with her three
    # saved pictures most like it.
    assert [gallery.names[owner] for owner in chosen] == ["412", "233", "87"]
    assert chosen[gallery.names.index("412")] == [
        ("412 on day 1", 1),
        ("412 on day 1", 2),
        ("412 on day 1", 0),
    ]
    assert chosen[gallery.names.index("233")] == [("233 on day 1", 0)]


def test_shared_coat_details_settle_what_the_embedding_leaves_too_close_to_call():
    # Similarities to 233 and 412.
    row = np.asarray([0.68, 0.7], np.float32)
    [unsure] = decide_together([row], [set()], [None], 0.3)
    assert not unsure.recognised

    # Details beyond a hundred count no further.
    fused = with_coat(row, {0: 150, 1: 10})
    np.testing.assert_allclose(fused, [0.88, 0.72])
    [sure] = decide_together([fused], [set()], [None], 0.3)
    assert sure.recognised and sure.scores.argmax() == 0


def test_the_threshold_is_set_on_sightings_compared_as_new_tracks_are():
    plain = self_set_threshold(herd([1, 2]), 0.99)
    assert plain is not None

    def compare(sighting, known):
        # Every sighting shares all its coat details with her own name only.
        similarities = known.similarities(sighting.vectors)
        if sighting.name not in known.names:
            return similarities
        return with_coat(similarities, {known.names.index(sighting.name): 100})

    assert self_set_threshold(herd([1, 2]), 0.99, compare=compare) == pytest.approx(
        plain + 0.2, abs=1e-6
    )
