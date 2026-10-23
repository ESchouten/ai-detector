import numpy as np
import pytest

from conftest import FakeEmbedder, FakeMatcher
from reid.adapt import Adaptation
from reid.benchmark import Options as BenchmarkOptions
from reid.benchmark import embeddings, self_set_thresholds
from reid.enrollment import (
    Options,
    _thresholds,
    cut,
    merge_tree,
    play_farmer,
    sightings,
    simulate,
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


def test_a_coat_weight_needs_a_matcher(herd):
    vectors = embeddings(herd, FakeEmbedder())

    with pytest.raises(ValueError, match="matcher"):
        simulate(herd, vectors, Options(coats=(0.5,)))
