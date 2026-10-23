import numpy as np

from reid.matching import identity_scores, runner_up_margin, track_scores


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


def test_the_runner_up_margin_takes_the_closest_rival_off_each_score():
    scores = np.array([[0.9, 0.7, 0.1], [0.5, 0.5, 0.2]], np.float32)

    np.testing.assert_allclose(
        runner_up_margin(scores, 1.0), [[0.2, -0.2, -0.8], [0.0, 0.0, -0.3]], atol=1e-6
    )
    np.testing.assert_allclose(
        runner_up_margin(scores, 0.5)[0], [0.55, 0.25, -0.35], atol=1e-6
    )
    assert runner_up_margin(scores, 0.0) is scores
    single = scores[:, :1]
    assert runner_up_margin(single, 1.0) is single
