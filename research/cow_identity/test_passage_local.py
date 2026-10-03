"""Parity and fixed threshold boundaries for the geometric passage control."""

import unittest

import cv2
import numpy as np
from local_features import extract, geometric_score
from passage_local_match import evidence, select


class LocalMatcherTest(unittest.TestCase):
    def test_detailed_matcher_preserves_legacy_scalar_score(self):
        rng = np.random.default_rng(20261003)
        image = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
        first = extract(image)
        affine = cv2.getRotationMatrix2D((160, 120), 10, 0.9)
        for other in (
            image.copy(),
            cv2.warpAffine(image, affine, (320, 240)),
            rng.integers(0, 256, image.shape, dtype=np.uint8),
            np.zeros_like(image),
        ):
            reference = extract(other)
            self.assertEqual(
                evidence(first, reference)["score"], geometric_score(first, reference)
            )

    def test_thresholds_compare_distinct_cow_inliers(self):
        def scores(first, second):
            return [
                {"identity_id": "a", "name": "cowA", "score": first},
                {"identity_id": "b", "name": "cowB", "score": second},
            ]

        self.assertEqual(select(scores(11, 6)).identity_id, "a")
        self.assertIsNone(select(scores(10, 0)).identity_id)
        self.assertIsNone(select(scores(11, 7)).identity_id)
        self.assertIsNone(select(scores(80, 80)).identity_id)


if __name__ == "__main__":
    unittest.main()
