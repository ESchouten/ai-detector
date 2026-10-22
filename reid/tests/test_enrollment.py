import numpy as np
import pytest

from conftest import FakeEmbedder
from reid.benchmark import embeddings
from reid.enrollment import Options, cut, merge_tree, play_farmer, sightings, simulate
from reid.manifest import Crop


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
    labelled = result["labelled"]
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
