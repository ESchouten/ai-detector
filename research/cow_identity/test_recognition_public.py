"""Keep public-cattle sampling separated by identity and recording day."""

import random
import unittest
from collections import Counter

import numpy as np
from recognition_farm_data import validate_rows
from recognition_public_finetune import prototype_weights, sample_batch, training_groups


class PublicTrainingTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "identity": f"{dataset}:{cow}",
                "dataset": dataset,
                "day": day,
                "split": "train" if cow < 4 else "validation_query",
            }
            for dataset in ("cows2021", "sideview2026")
            for cow in range(5)
            for day in range(3)
        ]

    def test_batch_has_cross_day_positives_and_same_dataset_negatives(self):
        _, groups, datasets = training_groups(self.rows)
        for seed in range(20):
            rows = sample_batch(groups, datasets, random.Random(seed))
            self.assertEqual(len(rows), 8)
            self.assertEqual(
                Counter(row["dataset"] for row in rows),
                {"cows2021": 4, "sideview2026": 4},
            )
            counts = Counter(row["identity"] for row in rows)
            self.assertEqual(len(counts), 4)
            self.assertEqual(set(counts.values()), {2})
            self.assertTrue(all(row["split"] == "train" for row in rows))
            for identity in counts:
                self.assertEqual(
                    len({row["day"] for row in rows if row["identity"] == identity}), 2
                )

    def test_identity_overlap_and_same_day_duplicates_are_rejected(self):
        overlap = [*self.rows, {**self.rows[0], "split": "validation_gallery"}]
        with self.assertRaisesRegex(ValueError, "identities overlap"):
            training_groups(overlap)
        with self.assertRaisesRegex(ValueError, "same-day"):
            training_groups([*self.rows, self.rows[0]])

    def test_prototype_initialization_excludes_validation_vectors(self):
        rows = [
            {"identity": "cow", "split": split}
            for split in ("train", "train", "validation_query")
        ]
        values = np.array([[1, 0], [0, 1], [1000, 1000]])
        np.testing.assert_array_equal(
            prototype_weights(rows, values, ["cow"]), [[0.5, 0.5]]
        )

    def test_farm_training_rejects_later_unknown_and_duplicate_photos(self):
        rows = [
            {
                "cow": cow,
                "identity": f"8calves-confirmed:{cow}",
                "panel": "enrollment",
                "second": second,
                "frame": second * 20 + 1,
                "box": [cow, 0, cow + 1, 1],
                "pixels_sha256": f"{cow}-{second}",
            }
            for cow in range(1, 7)
            for second in range(0, 50, 5)
        ]
        validate_rows(rows)
        for key, value in (("second", 330), ("panel", "development"), ("cow", 7)):
            changed = [{**row} for row in rows]
            changed[0][key] = value
            with self.assertRaises(ValueError):
                validate_rows(changed)
        with self.assertRaisesRegex(ValueError, "distinct early"):
            validate_rows([rows[1], *rows[1:]])


if __name__ == "__main__":
    unittest.main()
