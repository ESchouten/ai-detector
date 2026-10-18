import numpy as np

from reid.matching import identity_scores, track_scores


def test_an_animal_scores_by_her_nearest_pictures():
    similarity = np.array([[0.9, 0.1, 0.8, 0.7]], dtype=np.float32)

    names, scores = identity_scores(similarity, ["a", "a", "b", "b"], k=2)

    assert names == ("a", "b")
    np.testing.assert_allclose(scores, [[0.5, 0.75]])


def test_an_animal_with_one_picture_scores_by_it():
    similarity = np.array([[0.9, 0.4]], dtype=np.float32)

    _, scores = identity_scores(similarity, ["a", "b"], k=3)

    np.testing.assert_allclose(scores, [[0.9, 0.4]])


def test_tracks_average_their_crops_and_lone_crops_stay_apart():
    scores = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5], [0.2, 0.8]], np.float32)

    firsts, averaged = track_scores(scores, ["t1", "", "t1", ""])

    assert firsts == (0, 1, 3)
    np.testing.assert_allclose(averaged, [[0.75, 0.25], [0.0, 1.0], [0.2, 0.8]])
