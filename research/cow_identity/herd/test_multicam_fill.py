from multicam_fill import gaps, possible, rising


def test_pictures_take_frames_that_rise_with_them_and_the_closer_fit_wins_a_frame():
    # A cow stands still: her second and third picture both fit frames 10 and 15.
    nodes = [
        (0, 5, 5.0, "first on 5"),
        (1, 10, 5.1, "second on 10"),
        (1, 15, 5.3, "second on 15"),
        (2, 10, 5.2, "third on 10"),
        (2, 15, 5.4, "third on 15"),
        (3, 20, 5.0, "fourth on 20"),
    ]

    assert [entry for _, _, _, entry in rising(nodes)] == [
        "first on 5",
        "second on 10",
        "third on 15",
        "fourth on 20",
    ]


def test_a_picture_that_cannot_rise_is_left_out_and_nothing_gives_nothing():
    nodes = [(0, 900, 5.0, "a"), (1, 10_000_005, 5.0, "b"), (2, 950, 5.0, "c")]

    assert [entry for _, _, _, entry in rising(nodes)] == ["a", "b"]
    assert rising([]) == []


def test_a_picture_on_its_own_frame_is_worth_more_than_two_beside_theirs():
    # Three pictures of a cow that stands still. The third lies on its own frame, 10, which
    # the first two fit less closely; taking it there leaves room for only one of them.
    nodes = [
        (0, 10, 9.5, "first beside"),
        (1, 15, 9.6, "second beside"),
        (0, 5, 9.9, "first earlier"),
        (2, 10, 5.2, "third on its own"),
    ]

    assert [entry for _, _, _, entry in rising(nodes)] == ["first earlier", "third on its own"]


def test_a_gap_knows_the_placed_pictures_on_either_side():
    walk = ["p0", "p1", "p2", "p3", "p4", "p5"]
    placed = {"p1": {"frame": 10}, "p4": {"frame": 25}}

    assert gaps(walk, placed) == [
        ([0], None, {"frame": 10}),
        ([2, 3], {"frame": 10}, {"frame": 25}),
        ([5], {"frame": 25}, None),
    ]
    assert gaps(walk, {}) == []


def test_between_two_neighbours_a_picture_lies_about_as_far_along_as_its_place():
    before, after = {"clip": "a", "frame": 100}, {"clip": "a", "frame": 115}

    assert possible([4, 5], before, after) == {
        4: [("a", 105), ("a", 110)],
        5: [("a", 105), ("a", 110)],
    }


def test_beside_one_neighbour_a_picture_lies_at_least_its_distance_away():
    frames = possible([7, 8], {"clip": "a", "frame": 100}, None)

    assert frames[7][0] == ("a", 105) and frames[8][0] == ("a", 110)
    assert frames[7][-1] == ("a", 155)

    frames = possible([0, 1], None, {"clip": "b", "frame": 12})

    assert frames[0] == [("b", 0)] and frames[1] == [("b", 0), ("b", 5)]
