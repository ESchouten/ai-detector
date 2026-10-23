from dataclasses import replace

import numpy as np
import pytest

from conftest import FakeEmbedder, FakeMatcher
from reid.adapt import Adaptation
from reid.benchmark import Options as BenchmarkOptions
from reid.benchmark import embeddings, self_set_thresholds
from reid.calibration import Calibration, Pairs
from reid.enrollment import (
    Options,
    _thresholds,
    cut,
    merge_tree,
    named_jointly,
    play_farmer,
    sightings,
    simulate,
    together,
)
from reid.manifest import Crop
from reid.splits import Split


def _partition(labels) -> set[frozenset[int]]:
    groups: dict[int, set[int]] = {}
    for item, label in enumerate(labels):
        groups.setdefault(int(label), set()).add(item)
    return {frozenset(group) for group in groups.values()}


def _average_linkage(similarity, threshold) -> set[frozenset[int]]:
    """Join the two most similar groups by mean pairwise similarity, by brute force."""
    groups = [[item] for item in range(len(similarity))]
    while len(groups) > 1:
        best, pair = -np.inf, None
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                value = similarity[np.ix_(groups[a], groups[b])].mean()
                if value > best:
                    best, pair = value, (a, b)
        if best < threshold:
            break
        assert pair is not None
        a, b = pair
        groups[a] += groups.pop(b)
    return {frozenset(group) for group in groups}


def test_the_chain_finds_the_same_groups_as_brute_force():
    rng = np.random.default_rng(3)
    points = rng.normal(size=(30, 5))
    points /= np.linalg.norm(points, axis=1, keepdims=True)
    similarity = points @ points.T

    merges = merge_tree(similarity)

    assert len(merges) == 29
    for threshold in (-0.2, 0.0, 0.2, 0.4, 0.6, 0.9):
        assert _partition(cut(merges, 30, threshold)) == _average_linkage(
            similarity, threshold
        )


def test_cutting_high_keeps_every_item_apart_and_low_joins_them_all():
    similarity = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.2], [0.1, 0.2, 1.0]])
    merges = merge_tree(similarity)

    assert _partition(cut(merges, 3, 0.95)) == {
        frozenset({0}),
        frozenset({1}),
        frozenset({2}),
    }
    assert _partition(cut(merges, 3, 0.5)) == {frozenset({0, 1}), frozenset({2})}
    assert _partition(cut(merges, 3, 0.0)) == {frozenset({0, 1, 2})}
    assert merge_tree(np.ones((1, 1))) == []


def test_the_farmer_names_big_groups_first_after_the_cow_most_of_it_shows():
    # Group 0 mixes two sightings of a with one of b; groups 1 and 2 are c and b.
    groups = [0, 0, 0, 1, 2]
    cows = ["a", "a", "b", "c", "b"]
    sizes = [5, 5, 3, 4, 2]

    enrolment = play_farmer(groups, cows, sizes, goal=0.6)

    assert enrolment.groups == 3
    assert enrolment.taps == 2
    assert enrolment.names == ("a", "a", "a", "c", "")
    assert enrolment.milestones == {0.5: 2, 0.8: 3, 0.9: 3, 1.0: 3}
    assert enrolment.purity == pytest.approx(4 / 5)


def test_a_track_is_one_sighting_and_a_crop_without_one_stands_alone(herd):
    untracked = [Crop(herd[0].path, "cow0", "2026-10-01")] * 2
    crops = [*herd[:6], *untracked]

    assert sightings(crops, range(len(crops))) == [[0, 1, 2], [3, 4, 5], [6], [7]]


def test_a_separable_herd_is_enrolled_with_a_tap_per_cow_and_named_later(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))

    result = simulate(herd, vectors, Options(merges=(0.8, 0.999), goal=1.0))

    assert result["enrol_sessions"] == ["2026-10-01", "2026-10-02"]
    assert result["test_sessions"] == ["2026-10-03", "2026-10-04"]
    assert result["herd"] == 8
    assert result["sightings"] == 32
    (labelled,) = result["labelled"]
    assert labelled["level"] == "track"
    assert labelled["mean"]["recognised"] == 1.0
    assert labelled["mean"]["wrong"] == 0
    grouped, split = result["grouped"]
    assert (grouped["groups"], grouped["taps"], grouped["purity"]) == (8, 8, 1.0)
    assert grouped["gallery_right"] == 1.0
    assert grouped["mean"]["recognised"] == 1.0
    assert grouped["mean"]["wrong"] == 0
    assert [day["cows"] for day in grouped["days"]] == [8, 8]
    # Grouped too strictly, every sighting is its own group: the farmer taps far
    # more and still leaves cows with fewer pictures to be recognised by.
    assert split["groups"] == 32
    assert split["taps"] > 20
    assert split["mean"]["wrong"] == 0
    assert split["mean"]["recognised"] <= grouped["mean"]["recognised"]


def test_enrolment_needs_sessions_to_test_on(herd):
    vectors = embeddings(herd, FakeEmbedder())

    with pytest.raises(ValueError, match="more than 4"):
        simulate(herd, vectors, Options(enrol_sessions=4))


def test_a_runner_up_margin_still_names_a_separable_herd(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))

    result = simulate(herd, vectors, Options(merges=(0.8,), goal=1.0, margin=0.5))

    assert result["options"]["margin"] == 0.5
    assert result["grouped"][0]["mean"]["recognised"] == 1.0
    assert result["grouped"][0]["mean"]["wrong"] == 0


def test_the_install_sets_its_threshold_as_the_benchmark_does(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.4))
    enrolled = [i for i, crop in enumerate(herd) if crop.session < "2026-10-03"]
    crops = [herd[i] for i in enrolled]
    whole = Split("enrolled", tuple(range(len(crops))), (), frozenset(), True)

    benchmark = self_set_thresholds(
        crops, vectors[enrolled], [whole], BenchmarkOptions()
    )[0]

    assert _thresholds(crops, vectors[enrolled], None, Adaptation(), Options()) == {
        0.0: pytest.approx(benchmark["track"])
    }


def test_coat_matches_name_more_of_a_blurry_herd_and_rightly(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.6))
    matcher = FakeMatcher()

    result = simulate(
        herd, vectors, Options(merges=(0.8,), goal=1.0, coats=(0.0, 0.5)), matcher
    )

    alone, coat = result["labelled"]
    assert (alone["coat"], coat["coat"]) == (0.0, 0.5)
    assert alone["mean"]["wrong"] > 0
    assert coat["mean"]["wrong"] == 0
    assert coat["mean"]["named"] > alone["mean"]["named"]
    assert [entry["coat"] for entry in result["grouped"]] == [0.0, 0.5]
    assert result["options"]["matcher"] == "fake-matcher"
    assert matcher.pairs


def test_a_calibrated_mix_of_another_farm_is_tried_beside_the_coat_weights(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.6))
    options = Options(merges=(0.8,), goal=1.0, coats=(0.0, 0.5))
    other = simulate(herd, vectors, options, FakeMatcher())
    pairs = Pairs.of([other["pairs"]])
    # Every later sighting with its three re-checked cows.
    assert len(pairs.same) == 3 * 8 * 2 * 2
    assert pairs.same.sum() == 8 * 2 * 2

    calibration = Calibration.fit(pairs, ("other farm",))
    result = simulate(
        herd, vectors, replace(options, calibration=calibration), FakeMatcher()
    )

    alone, _, mixed = result["labelled"]
    assert mixed["coat"] == "calibrated"
    assert mixed["mean"]["wrong"] == 0
    assert mixed["mean"]["named"] > alone["mean"]["named"]
    assert result["options"]["calibrated_on"] == ["other farm"]


def test_a_floor_from_cows_seen_together_only_raises_the_threshold(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.9))
    options = Options(merges=(0.8,), goal=1.0, margin=0.75, times=TIMES)

    result = simulate(herd, vectors, replace(options, floor=(False, True)))

    plain, floored = result["labelled"]
    assert (plain["floored"], floored["floored"]) == (False, True)
    # Look-alikes seen beside each other while enrolling set the floor.
    assert floored["floor"] is not None
    assert floored["threshold"] > plain["threshold"]
    assert floored["mean"]["wrong"] <= plain["mean"]["wrong"]
    assert floored["mean"]["named"] <= plain["mean"]["named"]
    with pytest.raises(ValueError, match="times"):
        simulate(herd, vectors, Options(floor=(True,)))


def test_a_coat_weight_needs_a_matcher(herd):
    vectors = embeddings(herd, FakeEmbedder())

    with pytest.raises(ValueError, match="matcher"):
        simulate(herd, vectors, Options(coats=(0.5,)))


def test_the_install_can_check_its_threshold_on_every_enrolment_day(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))

    result = simulate(
        herd, vectors, Options(merges=(0.8,), goal=1.0, check="rotate", margin=0.75)
    )

    assert result["options"]["check"] == "rotate"
    for entry in (*result["labelled"], *result["grouped"]):
        assert entry["threshold"] is not None
        assert entry["mean"]["recognised"] > 0.9
        assert entry["mean"]["wrong"] == 0
    with pytest.raises(ValueError, match="threshold check"):
        simulate(herd, vectors, Options(check="guess"))


# In the herd's paths, the day is the clip and the track number the moment.
TIMES = r"/d(?P<clip>\d)-t(?P<frame>\d)-"


def test_sightings_of_the_same_moment_are_in_view_together(herd):
    seen = sightings(herd, range(len(herd)))
    others = together(herd, seen, TIMES)

    # cow0's first track on the first day is seen with every other cow's first
    # track that day, and with nothing else.
    first = seen.index([0, 1, 2])
    assert {herd[seen[other][0]].path.name for other in others[first]} == {
        "d0-t0-0.png"
    }
    assert len(others[first]) == 7
    assert together(herd, seen, r"/nothing-matches") == [set()] * len(seen)


def test_a_name_goes_to_one_of_the_sightings_in_view_together():
    # Both sightings look most like 412; the first more so. The third is seen
    # at another time.
    scores = np.array(
        [[0.9, 0.2, 0.1], [0.7, 0.6, 0.1], [0.7, 0.6, 0.1]], dtype=np.float32
    )
    real = np.array([True, True, True])
    others = [{1}, {0}, set()]

    jointly = named_jointly(scores, real, 0.45, 0.5, others)
    alone = named_jointly(scores, real, 0.45, 0.5, [set(), set(), set()])

    # Alone, the second is too close between 412 and 233 to be named. With 412
    # taken by the first, 233 is left without a rival.
    assert alone.tolist() == [0, -1, -1]
    assert jointly.tolist() == [0, 1, -1]


def test_an_anonymous_cow_competes_but_is_never_given():
    scores = np.array([[0.9, 0.2], [0.2, 0.9]], dtype=np.float32)
    real = np.array([True, False])

    assert named_jointly(scores, real, 0.5, 0.0, [set(), set()]).tolist() == [0, -1]


def test_naming_jointly_and_with_anonymous_cows_is_simulated_beside_naming_alone(
    herd,
):
    vectors = embeddings(herd, FakeEmbedder(noise=0.5))
    options = Options(
        merges=(0.8,),
        goal=0.7,
        margin=0.75,
        jointly=(False, True),
        times=TIMES,
        anonymous=(False, True),
    )

    result = simulate(herd, vectors, options)

    assert [(e["jointly"], e["anonymous"]) for e in result["labelled"]] == [
        (False, False),
        (True, False),
    ]
    entries = {(e["jointly"], e["anonymous"]): e for e in result["grouped"]}
    assert set(entries) == {(False, False), (True, False), (False, True), (True, True)}
    assert entries[(False, False)]["changed"] == 0
    alone, jointly = entries[(False, False)], entries[(True, False)]
    assert jointly["changed"] > 0
    assert jointly["mean"]["named"] >= alone["mean"]["named"]
    with pytest.raises(ValueError, match="times"):
        simulate(herd, vectors, Options(jointly=(True,)))
