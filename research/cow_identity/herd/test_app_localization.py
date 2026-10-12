from app_localization import nameable


def box(track, seconds):
    return {"track": track, "seconds": seconds}


def test_a_name_comes_after_fit_pictures_in_a_row_and_goes_with_the_first_unfit_one():
    boxes = [box(1, second * 0.2) for second in range(8)]
    fit = [True, True, True, True, False, True, True, False]

    assert nameable(boxes, fit, needed=3) == [False, False, True, True, False, False, False, False]


def test_a_name_can_be_taken_to_outlast_the_last_fit_picture_for_a_moment():
    boxes = [box(1, second) for second in (0.0, 0.2, 0.4, 0.6, 1.0, 3.0)]
    fit = [True, True, True, False, False, False]

    assert nameable(boxes, fit, needed=3, kept_unfit=1) == [False, False, True, True, True, False]


def test_tracks_are_counted_apart():
    boxes = [box(1, 0.0), box(2, 0.0), box(1, 0.2), box(2, 0.2)]

    assert nameable(boxes, [True, False, True, True], needed=2) == [False, False, True, False]
