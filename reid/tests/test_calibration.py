import numpy as np
import pytest

from reid.calibration import Calibration, Isotonic, Pairs


def test_isotonic_chances_rise_with_the_score_and_pool_what_does_not():
    calibrate = Isotonic.fit([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], [0, 1, 0, 0, 1, 1])

    # 0.2 to 0.4 hold one same cow of three, pooled into one chance.
    assert calibrate([0.1, 0.2, 0.3, 0.4, 0.6]) == pytest.approx(
        [0, 1 / 3, 1 / 3, 1 / 3, 1]
    )
    # Between and beyond the fitted scores.
    assert calibrate([0.45, -1.0, 2.0]) == pytest.approx([2 / 3, 0, 1])


def test_equal_scores_share_one_chance():
    calibrate = Isotonic.fit([0.5, 0.5, 0.5, 0.9], [1, 0, 0, 1])

    assert calibrate([0.5, 0.9]) == pytest.approx([1 / 3, 1])


def test_the_mix_is_the_mean_of_both_chances():
    pairs = Pairs(
        np.array([0.2, 0.4, 0.6, 0.8], np.float32),
        np.array([5, 50, 10, 90], np.float32),
        np.array([False, True, False, True]),
    )
    calibration = Calibration.fit(pairs, ("other farm",))

    # The embedding alone is unsure at 0.6; the coat check says no.
    assert calibration.fuse([0.6, 0.8], [10, 90]) == pytest.approx([0.25, 1.0])


def test_pairs_of_several_runs_are_pooled():
    run = Pairs(
        np.array([0.2], np.float32), np.array([5], np.float32), np.array([False])
    ).record()

    pooled = Pairs.of([run, {**run, "same": [True]}])

    assert pooled.same.tolist() == [False, True]
    assert pooled.deep == pytest.approx([0.2, 0.2])
