from collections import Counter

from multicam_walks import walks


def test_a_walk_is_named_when_one_picture_of_it_carries_her_name():
    # Cow 1 is named in one of three pictures, cow 2 is found and never named, cow 3 is not
    # found at all. Cow 8 is unknown and walks by unnamed; unknown cow 12 is taken for cow 2.
    partner = [1, 1, 1, 2, 2, 8, 12, None]
    shown = [None, 1, None, None, None, None, 2, 1]
    visible = Counter({1: 3, 2: 2, 3: 4, 8: 1, 12: 1})

    result = walks(shown, partner, visible, {1, 2, 3})

    assert result["pictures_of_enrolled_cows"] == 9
    assert result["pictures_that_carry_her_name"] == 1
    assert result["enrolled_cows_that_walk_by"] == 3
    assert result["named_as_herself"] == 1
    assert result["named_as_another_cow"] == 0
    assert result["never_found"] == 1
    assert result["not_named"] == [2, 3]
    assert result["unknown_cows_that_walk_by"] == 2
    assert result["unknown_cows_named"] == [12]


def test_a_cow_shown_as_another_counts_as_named_wrongly_even_if_also_named_right():
    result = walks([1, 2, None], [1, 1, 2], Counter({1: 2, 2: 1}), {1, 2})

    assert result["named_as_herself"] == 1
    assert result["named_as_another_cow"] == 1
    assert result["not_named"] == [2]
