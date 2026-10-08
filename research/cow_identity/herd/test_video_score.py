from video_score import score_frame, summarise

ENROLLED = {1, 2}
TRUTH = [(1, 0, 0, 10, 10), (2, 20, 0, 30, 10), (9, 40, 0, 50, 10)]


def counts(predictions):
    return score_frame(TRUTH, predictions, ENROLLED)[0]


def test_a_name_is_correct_only_on_the_animal_it_names():
    result = counts(
        [
            {"box": (0, 0, 10, 10), "name": 1},
            {"box": (20, 0, 30, 10), "name": 1},
        ]
    )
    assert result["correct"] == 1
    assert result["wrong_enrolled"] == 1


def test_names_on_withheld_and_unannotated_animals_are_kept_apart():
    result = counts(
        [
            {"box": (40, 0, 50, 10), "name": 2},
            {"box": (70, 0, 80, 10), "name": 2},
            {"box": (0, 0, 10, 10), "name": None},
        ]
    )
    assert result["named_withheld"] == 1
    assert result["named_unannotated"] == 1
    assert result["located_enrolled"] == 1
    assert result["correct"] == 0


def test_missed_animals_stay_in_the_coverage_denominator():
    summary = summarise(counts([{"box": (0, 0, 10, 10), "name": 1}]))
    assert summary["coverage"] == 0.5
    assert summary["precision"] == 1.0
    assert summary["withheld_named"] == 0.0
    assert summary["localization_recall"] == 1 / 3


def test_a_name_no_annotation_can_judge_lowers_only_the_conservative_precision():
    summary = summarise(
        counts(
            [
                {"box": (20, 0, 30, 10), "name": 2},
                {"box": (70, 0, 80, 10), "name": 7},
            ]
        )
    )
    assert summary["unpaired_unjudged"] == 1
    assert summary["precision"] == 1.0
    assert summary["precision_conservative"] == 0.5


def test_a_loose_box_is_judged_by_the_animal_it_lies_on():
    loose = (4, 0, 14, 10)  # overlaps cow 1, but too little to pair with it
    right = summarise(counts([{"box": loose, "name": 1}]))
    assert (right["unpaired_on_named"], right["precision"]) == (1, None)
    assert right["coverage"] == 0.0

    wrong = summarise(counts([{"box": (0, 0, 10, 10), "name": 1}, {"box": (24, 0, 34, 10), "name": 1}]))
    assert (wrong["unpaired_on_other"], wrong["precision"]) == (1, 0.5)

    stranger = summarise(counts([{"box": (44, 0, 54, 10), "name": 2}]))
    assert stranger["unpaired_on_withheld"] == 1
    assert stranger["withheld_named"] == 1.0


def test_a_name_far_from_its_annotated_cow_is_an_error():
    summary = summarise(
        counts([{"box": (0, 0, 10, 10), "name": 1}, {"box": (70, 0, 80, 10), "name": 1}])
    )
    assert summary["unpaired_elsewhere"] == 1
    assert summary["precision"] == 0.5

    # Merely touching a neighbour is not lying on it.
    touching = summarise(counts([{"box": (28, 0, 38, 10), "name": 7}]))
    assert (touching["unpaired_on_other"], touching["unpaired_unjudged"]) == (0, 1)


def test_ignored_animals_and_their_boxes_count_nowhere():
    result = score_frame(
        TRUTH,
        [{"box": (40, 0, 50, 10), "name": 2}, {"box": (0, 0, 10, 10), "name": 1}],
        ENROLLED,
        ignored={9},
    )[0]
    assert result["named_withheld"] == 0
    assert result["visible_withheld"] == 0
    assert result["correct"] == 1

    loose = score_frame(TRUTH, [{"box": (44, 0, 54, 10), "name": 2}], ENROLLED, ignored={9})[0]
    assert loose["named_unannotated"] == 0
