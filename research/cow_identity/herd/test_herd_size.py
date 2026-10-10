import numpy as np

import multicam
from herd_size import herd, named, told_apart, walks_named


def test_a_smaller_herd_is_part_of_a_larger_one_and_holds_no_withheld_cow():
    present = multicam.COWS[:-1]

    assert set(herd(12, present)) < set(herd(30, present)) < set(herd(67, present))
    assert len(herd(12, present)) == 12
    assert not set(herd(67, present)) & {*multicam.WITHHELD, multicam.COWS[-1]}


def test_a_picture_counts_when_it_resembles_its_own_cow_most_and_enough():
    cows = [1, 2]
    # Cow 4 is withheld: one of her pictures passes the limit.
    truth = np.array([1, 1, 2, 4, 4])
    similarity = np.array([[0.9, 0.2], [0.3, 0.7], [0.1, 0.5], [0.65, 0.1], [0.2, 0.3]])

    result = told_apart(similarity, cows, truth, 0.6)

    assert result["pictures_of_enrolled_cows"] == 3
    assert result["pictures_of_withheld_cows"] == 2
    assert result["resemble_their_own_cow_most"] == 2 / 3
    assert result["and_are_similar_enough"] == 1 / 3
    assert result["resemble_another_cow_and_are_similar_enough"] == 1 / 3
    assert result["withheld_that_are_similar_enough"] == 1 / 2


def test_a_name_needs_pictures_in_a_row_that_agree_and_pass():
    passes = [True] * 6

    assert named([1, 1, 1, 2, 2, 2], passes, 3) == {1: 2, 2: 5}
    assert named([1, 1, 2, 1, 1, 2], passes, 3) == {}
    assert named([1, 1, 1, 1, 1, 1], [True, True, False, True, True, True], 3) == {1: 5}


def test_walks_are_counted_at_the_pictures_the_application_would_see():
    cows = [1, 2]
    # Cow 1 walks by in six pictures, withheld cow 4 in four that all resemble cow 2.
    rows = [{"cow": 1, "walk": 0}] * 6 + [{"cow": 4, "walk": 1}] * 4
    similarity = np.array([[0.9, 0.1]] * 6 + [[0.1, 0.8]] * 4)

    every_picture = walks_named(similarity, cows, rows, 0.6, 3, 1)
    every_other = walks_named(similarity, cows, rows, 0.6, 3, 2)

    assert every_picture["named_as_herself"] == 1
    assert every_picture["pictures_that_carry_her_name"] == 4
    assert every_picture["withheld_named"] == 1
    assert every_other["pictures_of_enrolled_cows"] == 3
    assert every_other["pictures_that_carry_her_name"] == 1
    assert every_other["withheld_named"] == 0
