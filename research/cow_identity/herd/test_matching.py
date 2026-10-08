from matching import match, overlap


def test_overlap_of_identical_and_disjoint_boxes():
    scores = overlap([(0, 0, 10, 10)], [(0, 0, 10, 10), (20, 20, 30, 30)])
    assert scores.tolist() == [[1.0, 0.0]]


def test_count_of_pairs_comes_before_overlap():
    # Taking the perfect pair first would leave the second animal with a
    # prediction that overlaps it too little.
    truth = [(0, 0, 10, 10), (0, 0, 10, 6)]
    predicted = [(0, 0, 10, 10), (0, 0, 10, 13)]
    assert sorted(match(truth, predicted)) == [(0, 1), (1, 0)]


def test_pairs_below_the_threshold_are_dropped():
    assert match([(0, 0, 10, 10)], [(6, 0, 16, 10)]) == []
    assert match([], [(0, 0, 1, 1)]) == []
