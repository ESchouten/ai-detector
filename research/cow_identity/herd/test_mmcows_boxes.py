import numpy as np

from mmcows_boxes import told_apart


def test_a_crop_counts_when_its_own_cow_is_nearest_and_it_stands_out_from_strangers():
    cows = [1, 2]
    # Cow 4 is withheld: her crops show how high a stranger scores.
    truth = np.array([1, 1, 2, 4, 4])
    similarity = np.array([[0.9, 0.2], [0.3, 0.6], [0.1, 0.5], [0.55, 0.1], [0.2, 0.3]])

    result = told_apart(similarity, cows, truth, np.ones(5, dtype=bool))

    assert result["crops_of_enrolled_cows"] == 3
    assert result["crops_of_withheld_cows"] == 2
    assert result["resemble_their_own_cow_most"] == 2 / 3
    # Only the first crop is right and above the strangers' 0.55.
    assert result["and_score_above_99_in_100_strangers"] == 1 / 3


def test_only_the_chosen_crops_are_counted():
    truth = np.array([1, 2, 4, 4])
    similarity = np.array([[0.9, 0.2], [0.8, 0.1], [0.3, 0.1], [0.99, 0.1]])

    result = told_apart(similarity, [1, 2], truth, np.array([True, False, True, False]))

    assert result["crops_of_enrolled_cows"] == 1
    assert result["crops_of_withheld_cows"] == 1
    assert result["and_score_above_99_in_100_strangers"] == 1.0
