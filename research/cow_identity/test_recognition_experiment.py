"""Leakage and causal pooling checks for the public-video research panel."""

import unittest

import numpy as np
from recognition_experiment import pooled_queries, select_gallery
from recognition_features import PANELS
from recognition_temporal import temporal_names
from scoring import Scores


class RecognitionExperimentTest(unittest.TestCase):
    def test_untracked_boxes_never_share_temporal_confirmation(self):
        rows = [{"cow": 1, "track": None, "second": i} for i in range(6)]
        scores = Scores(
            np.ones(6),
            np.ones(6),
            np.full(6, 0.8),
            np.full(6, 0.2),
            np.ones(6, dtype=bool),
            np.zeros(6),
        )
        np.testing.assert_array_equal(
            temporal_names(rows, scores, 0.65, 0.1, 30), np.zeros(6)
        )

    def test_temporal_name_expires_and_resets_after_contradictory_evidence(self):
        rows = [{"cow": 1, "track": 42, "second": i} for i in range(7)]
        scores = Scores(
            np.ones(7),
            np.ones(7),
            np.array([0.8] * 3 + [0.1] * 4),
            np.full(7, 0.2),
            np.ones(7, dtype=bool),
            np.zeros(7),
        )
        np.testing.assert_array_equal(
            temporal_names(rows, scores, 0.65, 0.1, 2), [0, 0, 1, 1, 1, 0, 0]
        )
        truth_changed = [{**row, "cow": 999} for row in rows]
        np.testing.assert_array_equal(
            temporal_names(truth_changed, scores, 0.65, 0.1, 2),
            temporal_names(rows, scores, 0.65, 0.1, 2),
        )
        scores.predicted[3] = 2
        scores.similarity[3] = 0.8
        np.testing.assert_array_equal(
            temporal_names(rows, scores, 0.65, 0.1, 30), [0, 0, 1, 0, 0, 0, 0]
        )

    def test_temporal_policy_rejects_two_tracks_claiming_one_identity(self):
        rows = [
            {"cow": cow, "track": cow + 100, "second": second}
            for second in range(4)
            for cow in (1, 2)
        ]
        scores = Scores(
            np.array([row["cow"] for row in rows]),
            np.ones(8),
            np.full(8, 0.8),
            np.full(8, 0.2),
            np.ones(8, dtype=bool),
            np.zeros(8),
        )
        np.testing.assert_array_equal(
            temporal_names(rows, scores, 0.65, 0.1, 30), np.zeros(8)
        )

    def test_final_windows_are_not_available_to_development_extractor(self):
        seen = {second for seconds in PANELS.values() for second in seconds}
        self.assertTrue(seen.isdisjoint(range(1800, 2100)))
        self.assertTrue(seen.isdisjoint(range(2700, 3000)))

    def test_gallery_has_at_most_ten_early_known_examples_per_identity(self):
        rows = [
            {
                "panel": panel,
                "cow": cow,
                "second": second,
                "overlap": 0,
                "clipped": False,
            }
            for panel in ("enrollment", "calibration")
            for cow in range(1, 9)
            for second in range(0, 100, 5)
        ]
        rng = np.random.default_rng(42)
        vectors = rng.normal(size=(len(rows), 16))
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        for method in ("legacy3", "uniform10", "diverse5", "diverse10"):
            chosen = [rows[i] for i in select_gallery(rows, vectors, method)]
            self.assertTrue(all(row["panel"] == "enrollment" for row in chosen))
            self.assertTrue(all(row["cow"] <= 6 for row in chosen))
            for cow in range(1, 7):
                self.assertLessEqual(sum(row["cow"] == cow for row in chosen), 10)

    def test_pooling_is_causal_and_does_not_cross_tracks_or_windows(self):
        rows = [
            {"panel": "a", "cow": 1, "second": 0},
            {"panel": "a", "cow": 2, "second": 0},
            {"panel": "a", "cow": 1, "second": 1},
            {"panel": "b", "cow": 1, "second": 2},
            {"panel": "a", "cow": 1, "second": 9},
        ]
        vectors = np.array([[1, 0], [0, 1], [0, 1], [0, 1], [1, 0]], dtype=float)
        pooled = pooled_queries(rows, vectors, 3)
        np.testing.assert_allclose(pooled[:2], vectors[:2])
        np.testing.assert_allclose(pooled[2], [1 / np.sqrt(2), 1 / np.sqrt(2)])
        np.testing.assert_allclose(pooled[3:], vectors[3:])


if __name__ == "__main__":
    unittest.main()
