import numpy as np

from collections import Counter

from app_policy import Rules, fit_crops, funnel, name_crops


def crop(second, box, track, infrared=False):
    return {
        "index": second * 15,
        "seconds": float(second),
        "box": list(box),
        "track": track,
        "frame_size": [1000, 600],
        "infrared": infrared,
    }


CLEAR_A = [0.9, 0.2, 0.1]
CLEAR_B = [0.2, 0.9, 0.1]
FOREIGN = [0.6, 0.2, 0.9]
RULES = Rules(min_similarity=0.5, min_margin=0.3, min_observations=2)


def test_a_track_is_named_after_consecutive_agreeing_crops():
    crops = [crop(second, (100, 100, 300, 300), 1) for second in range(3)]
    names, _ = name_crops(crops, np.array([CLEAR_A] * 3), [7, 8], RULES)
    assert names == [None, 7, 7]


def test_two_animals_claiming_one_cow_both_stay_unknown():
    crops = [
        crop(second, box, track)
        for second in range(3)
        for track, box in ((1, (100, 100, 300, 300)), (2, (500, 100, 700, 300)))
    ]
    names, _ = name_crops(crops, np.array([CLEAR_A, CLEAR_A] * 3), [7, 8], RULES)
    assert names == [None] * 6


def test_an_animal_that_looks_most_like_another_farms_cow_is_unknown():
    crops = [crop(second, (100, 100, 300, 300), 1) for second in range(3)]
    names, _ = name_crops(crops, np.array([FOREIGN] * 3), [7, 8], RULES)
    assert names == [None, None, None]


def test_small_and_overlapping_boxes_are_no_evidence():
    crops = [
        crop(0, (100, 100, 300, 300), 1),
        crop(0, (150, 150, 320, 320), 2),
        crop(0, (600, 100, 640, 300), 3),
        crop(0, (0, 350, 200, 550), 4),
    ]
    assert fit_crops(crops, Rules(0.5, 0.3, max_overlap=0.2)) == [False, False, False, True]
    assert fit_crops(crops, Rules(0.5, 0.3, whole_animal=True))[3] is False
    assert fit_crops(crops, Rules(0.5, 0.3))[:2] == [True, True]


def test_the_funnel_counts_where_an_enrolled_animal_is_lost():
    crops = [crop(second, (100, 100, 300, 300), 1) for second in range(3)]
    _, stages = name_crops(crops, np.array([CLEAR_A, FOREIGN, CLEAR_A]), [7, 8], RULES)
    counts = funnel(stages, [7, 7, 7], Counter({7: 4}), Counter({7: 3}), {7})
    assert counts == {
        "visible": 4,
        "located": 3,
        "fit_crop": 3,
        "resembles_itself": 3,
        "accepted_candidate": 2,
        "unchallenged": 2,
        "shown": 0,
    }


def test_a_confirmed_name_is_held_through_weaker_crops_unless_someone_claims_it():
    weaker = [0.6, 0.5, 0.1]
    rules = Rules(min_similarity=0.5, min_margin=0.3, min_observations=2, hold=10)
    crops = [crop(second, (100, 100, 300, 300), 1) for second in range(4)]
    names, _ = name_crops(crops, np.array([CLEAR_A, CLEAR_A, weaker, weaker]), [7, 8], rules)
    assert names == [None, 7, 7, 7]

    rival = crop(3, (500, 100, 700, 300), 2)
    names, _ = name_crops(
        [*crops, rival], np.array([CLEAR_A, CLEAR_A, weaker, weaker, CLEAR_A]), [7, 8], rules
    )
    assert names == [None, 7, 7, None, None]


def test_a_track_missing_from_one_frame_keeps_its_agreement_as_in_the_application():
    crops = [crop(second, (100, 100, 300, 300), 1) for second in (0, 1, 3, 4)]
    scores = np.array([CLEAR_A] * 4)
    names, _ = name_crops(crops, scores, [7, 8], RULES, empty_frames=[2.0])
    assert names == [None, 7, 7, 7]

    # The rule the application had before: any missed frame starts the track over.
    strict = Rules(min_similarity=0.5, min_margin=0.3, min_observations=2, forget_absent=True)
    names, _ = name_crops(crops, scores, [7, 8], strict, empty_frames=[2.0])
    assert names == [None, 7, None, 7]

    other = crop(2, (500, 100, 700, 300), 2)
    names, _ = name_crops(
        [*crops[:2], other, *crops[2:]],
        np.array([CLEAR_A] * 2 + [CLEAR_B] + [CLEAR_A] * 2),
        [7, 8],
        strict,
    )
    assert names == [None, 7, None, None, 7]


def test_infrared_pictures_have_their_own_limit():
    rules = Rules(
        min_similarity=0.5, min_margin=0.3, min_observations=2, min_similarity_infrared=0.95
    )
    by_day = [crop(second, (100, 100, 300, 300), 1) for second in range(2)]
    by_night = [crop(second, (100, 100, 300, 300), 1, infrared=True) for second in range(2)]
    scores = np.array([CLEAR_A] * 2)
    assert name_crops(by_day, scores, [7, 8], rules)[0] == [None, 7]
    assert name_crops(by_night, scores, [7, 8], rules)[0] == [None, None]
    assert name_crops(by_night, scores, [7, 8], RULES)[0] == [None, 7]
