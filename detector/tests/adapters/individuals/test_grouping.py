import numpy as np

from aidetector.adapters.individuals.grouping import group


def unit(*values):
    vector = np.asarray(values, np.float32)
    return vector / np.linalg.norm(vector)


def at(degrees):
    return unit(np.cos(np.radians(degrees)), np.sin(np.radians(degrees)))


def average_linkage(vectors, similarity):
    """Every pair of groups compared at every step: slow, but plainly right."""
    pairs = vectors @ vectors.T
    groups = [[item] for item in range(len(vectors))]
    while len(groups) > 1:
        joined, first, second = max(
            (pairs[np.ix_(a, b)].mean(), i, j)
            for i, a in enumerate(groups)
            for j, b in enumerate(groups)
            if i < j
        )
        if joined < similarity:
            break
        groups[first] += groups.pop(second)
    return groups


def test_look_alike_sightings_form_groups_largest_first():
    vectors = np.stack(
        [
            unit(1, 0, 0),
            unit(0, 1, 0),
            unit(0.95, 0.05, 0),
            unit(0, 0.9, 0.1),
            unit(1, 0.1, 0),
            unit(0, 0, 1),
        ]
    )
    assert group(vectors) == [[0, 2, 4], [1, 3], [5]]


def test_a_chain_of_look_alikes_is_not_one_group_unless_it_looks_alike_on_average():
    # Neighbours look alike, but the ends do not: on average the last does not
    # look enough like the first two.
    chain = np.stack([at(0), at(35), at(72)])
    assert group(chain) == [[0, 1], [2]]
    assert group(chain, similarity=0.5) == [[0, 1, 2]]


def test_groups_are_those_of_average_linkage_cut_at_the_similarity():
    rng = np.random.default_rng(3)
    centres = rng.normal(size=(6, 8))
    vectors = centres[rng.integers(0, 6, 60)] + rng.normal(0, 0.6, (60, 8))
    vectors = (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(
        np.float32
    )
    expected = average_linkage(vectors, 0.6)
    assert 1 < len(expected) < len(vectors)
    assert sorted(map(sorted, group(vectors))) == sorted(map(sorted, expected))


def test_a_single_sighting_is_a_group_of_its_own():
    assert group(np.stack([unit(1, 0)])) == [[0]]
