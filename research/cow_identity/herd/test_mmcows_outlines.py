from mmcows_outlines import numbered


def test_a_found_cow_takes_the_number_of_the_box_it_overlaps_most():
    truth = [(7, 0, 0, 100, 100), (9, 200, 0, 300, 100)]
    found = [[205, 0, 300, 100], [0, 0, 100, 90]]

    assert numbered(found, truth) == {0: 9, 1: 7}


def test_a_box_that_overlaps_no_cow_by_half_stays_without_a_number():
    truth = [(7, 0, 0, 100, 100)]
    found = [[60, 0, 160, 100], [300, 300, 400, 400]]

    assert numbered(found, truth) == {}


def test_two_found_boxes_on_one_cow_do_not_both_take_her_number():
    truth = [(7, 0, 0, 100, 100)]
    found = [[0, 0, 100, 80], [0, 0, 100, 95]]

    assert numbered(found, truth) == {1: 7}
