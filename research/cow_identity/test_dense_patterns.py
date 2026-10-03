import numpy as np
from dense_patterns import reciprocal_score


def test_repeated_patch_cannot_manufacture_identity_support():
    positions = np.array([[0.1, 0.1], [0.1, 0.9], [0.9, 0.1], [0.9, 0.9]])
    assert reciprocal_score(np.ones((4, 4)), positions, positions) == 0
    assert reciprocal_score(np.eye(4), positions, positions) == 1


def test_matching_one_small_body_region_is_insufficient():
    positions = np.array([[0.1, 0.1], [0.1, 0.2], [0.2, 0.1], [0.2, 0.2]])
    assert reciprocal_score(np.eye(4), positions, positions) == 0
    assert reciprocal_score(np.empty((0, 4)), positions[:0], positions) == 0
