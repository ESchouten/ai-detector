"""Cohort isolation, chronology and duplicate checks without public data I/O."""

import unittest

from cattle_training_prepare import select_cohort, validate_manifest


class CattleTrainingPreparationTest(unittest.TestCase):
    def test_selection_is_stable_identity_disjoint_and_cross_day(self):
        rows = [
            {
                "dataset": dataset,
                "identity": f"{dataset}:{cow}",
                "day": f"2020-02-{day:02d}",
                "group": f"{dataset}:{cow}:2020-02-{day:02d}",
                "source_path": f"{dataset}/{cow}/{day}/{frame}.jpg",
            }
            for dataset in ("a", "b")
            for cow in range(10)
            for day in range(1, 21)
            for frame in range(3)
        ]
        selected, cohort = select_cohort(rows)
        self.assertEqual((selected, cohort), select_cohort(list(reversed(rows))))
        self.assertEqual(len(selected), 20 * 16)
        self.assertEqual(len(cohort["training_identities"]), 16)
        self.assertEqual(len(cohort["validation_identities"]), 4)
        self.assertEqual(len({row["group"] for row in selected}), len(selected))
        training = set(cohort["training_identities"])
        self.assertFalse(training & set(cohort["validation_identities"]))
        for identity in cohort["validation_identities"]:
            samples = [row for row in selected if row["identity"] == identity]
            gallery = [
                row["day"] for row in samples if row["split"] == "validation_gallery"
            ]
            query = [
                row["day"] for row in samples if row["split"] == "validation_query"
            ]
            if identity in cohort["validation_unknown_identities"]:
                self.assertFalse(gallery)
                self.assertEqual(len(query), 16)
            else:
                self.assertLess(max(gallery), min(query))

    def test_anonymous_namespaces_and_insufficient_days_are_not_invented(self):
        rows = [
            {"identity": "cows2021:000", "day": str(day), "source_path": str(day)}
            for day in range(4)
        ]
        selected, cohort = select_cohort(rows)
        self.assertEqual(selected, [])
        self.assertEqual(cohort["excluded_insufficient_days"], ["cows2021:000"])

    def test_manifest_rejects_identity_leakage_and_duplicated_pixels(self):
        first = {
            "identity": "a:001",
            "group": "a:001:day1",
            "split": "train",
            "pixels_sha256": "different-crop-one",
        }
        second = {
            "identity": "b:001",
            "group": "b:001:day2",
            "split": "validation_query",
            "pixels_sha256": "different-crop-two",
        }
        validate_manifest([first, second])
        with self.assertRaisesRegex(ValueError, "training and validation"):
            validate_manifest([first, {**second, "identity": "a:001"}])
        with self.assertRaisesRegex(ValueError, "conflicting identity"):
            validate_manifest(
                [first, {**second, "pixels_sha256": first["pixels_sha256"]}]
            )
        with self.assertRaisesRegex(ValueError, "Duplicate pixel"):
            validate_manifest([first, {**first, "group": "a:001:day2"}])


if __name__ == "__main__":
    unittest.main()
