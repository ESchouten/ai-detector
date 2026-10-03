"""Fusion must keep real observations and a shared gallery/query representation."""

import copy
import unittest

from recognition_fusion import align_observations, fusion_contract


class FusionTest(unittest.TestCase):
    def setUp(self):
        self.left = {
            "contract": {"encoder_fingerprint": "raw", "tracking_sha256": "scene-a"},
            "rows": [
                {
                    "frame": 6601,
                    "second": 330,
                    "box": [i * 10, 0, i * 10 + 9, 9],
                    "track": i,
                    "pixels_sha256": f"photo-{i}",
                    "truth": None,
                }
                for i in range(2)
            ],
            "frames": [{"second": 330, "rows": [0, 1], "truth": []}],
        }
        self.right = copy.deepcopy(self.left)
        self.right["contract"] = {
            "encoder_fingerprint": "data-specific-cache-key",
            "representation_fingerprint": "masked-representation",
        }
        self.right["rows"].reverse()

    def test_alignment_preserves_unmatched_boxes_and_ignores_truth_labels(self):
        self.right["rows"][0]["truth"] = 8
        self.assertEqual(align_observations(self.left, self.right), ([0, 1], [1, 0]))
        self.right["rows"][0]["pixels_sha256"] = "different-photo"
        with self.assertRaisesRegex(ValueError, "changed"):
            align_observations(self.left, self.right)

    def test_tracked_fusion_rejects_missing_or_duplicate_predictions(self):
        self.right["rows"].pop()
        with self.assertRaisesRegex(ValueError, "every predicted box"):
            align_observations(self.left, self.right)
        self.right["rows"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicated"):
            align_observations(self.left, self.right)

    def test_fingerprint_tracks_representation_not_dataset(self):
        original = fusion_contract(self.left, self.right)
        self.left["contract"]["tracking_sha256"] = "scene-b"
        self.right["contract"]["encoder_fingerprint"] = "another-cache-key"
        self.assertEqual(original, fusion_contract(self.left, self.right))
        self.right["contract"]["representation_fingerprint"] = "changed-model"
        self.assertNotEqual(original, fusion_contract(self.left, self.right))


if __name__ == "__main__":
    unittest.main()
