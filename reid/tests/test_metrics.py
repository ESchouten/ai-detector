import numpy as np
import pytest

from reid.metrics import Decisions, mean_average_precision, rank1, top_k


def test_rank1_counts_only_enrolled_queries():
    scores = np.array([[0.9, 0.1], [0.2, 0.8], [0.6, 0.4]], np.float32)

    assert rank1(("a", "b"), scores, ["a", "a", "stranger"]) == 0.5


def test_top_k_counts_the_own_animal_among_the_best_k():
    scores = np.array([[0.9, 0.5, 0.1], [0.1, 0.5, 0.9], [0.9, 0.5, 0.1]], np.float32)
    names = ("a", "b", "c")

    assert top_k(names, scores, ["b", "a", "stranger"], 1) == 0.0
    assert top_k(names, scores, ["b", "a", "stranger"], 2) == 0.5
    assert top_k(names, scores, ["b", "a", "stranger"], 3) == 1.0


def test_mean_average_precision():
    similarity = np.array([[0.9, 0.8, 0.7], [0.1, 0.2, 0.3]], np.float32)

    value = mean_average_precision(similarity, ["a", "b", "a"], ["a", "x"])

    assert value == pytest.approx((1 + 2 / 3) / 2)


def test_a_threshold_names_counts_wrong_names_and_strangers():
    scores = np.array([[0.9, 0.1], [0.3, 0.7], [0.8, 0.2], [0.4, 0.6]], np.float32)
    decisions = Decisions.of(("a", "b"), scores, ["a", "a", "stranger", "b"])

    naming = decisions.at(0.65)

    assert naming.named == 3
    assert naming.wrong == 2
    assert naming.coverage == pytest.approx(1 / 3)
    assert naming.precision == pytest.approx(1 / 3)
    assert naming.strangers_named == 1.0


def test_threshold_for_precision_is_the_lowest_that_keeps_it():
    scores = np.array(
        [[0.95, 0.0], [0.9, 0.0], [0.8, 0.0], [0.7, 0.0], [0.6, 0.0]], np.float32
    )
    decisions = Decisions.of(("a", "b"), scores, ["a", "a", "x", "a", "a"])

    assert decisions.threshold_for(1.0) == pytest.approx(0.9)
    assert decisions.threshold_for(0.85) == pytest.approx(0.9)
    assert decisions.threshold_for(0.8) == pytest.approx(0.6)


def test_equal_scores_are_named_together():
    scores = np.array([[0.9, 0.0], [0.9, 0.0]], np.float32)
    decisions = Decisions.of(("a", "b"), scores, ["a", "x"])

    assert decisions.threshold_for(1.0) is None
    assert decisions.threshold_for(0.5) == pytest.approx(0.9)
