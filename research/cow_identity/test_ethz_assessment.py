"""Source-index and metric contracts for the bounded adult-cow regression."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from ethz_gallery_audit import camera_audit
from ethz_localization import localization_metrics
from ethz_oracle import source_frames


class EthzAssessmentTest(unittest.TestCase):
    def test_source_frames_uses_zero_based_indices_without_seek_offsets(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "video.avi"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"MJPG"), 12.5, (32, 24)
            )
            self.assertTrue(writer.isOpened())
            try:
                for index in range(6):
                    writer.write(np.full((24, 32, 3), index * 30, dtype=np.uint8))
            finally:
                writer.release()
            source = {"path": path, "video": "synthetic", "stream_frames": 6}
            decoded = list(source_frames(source, {0, 3, 5}))
            self.assertEqual([row[0] for row in decoded], [0, 3, 5])
            for index, _, pixels in decoded:
                self.assertAlmostEqual(float(pixels.mean()), index * 30, delta=2)
            with self.assertRaisesRegex(ValueError, "frame count changed"):
                list(source_frames({**source, "stream_frames": 7}, {0}))

    def test_localization_counts_one_to_one_matches_without_claiming_exhaustive_truth(
        self,
    ):
        result = localization_metrics(
            [
                {
                    "video": "example",
                    "truth": [
                        {"cow": 0, "box": [0, 0, 10, 10]},
                        {"cow": 5, "box": [10, 0, 20, 10]},
                    ],
                    "boxes": [[0, 0, 20, 10], [30, 0, 40, 10], [10, 0, 20, 10]],
                    "confidence": [0.7, 0.9, 0.15],
                }
            ],
            [{"video": "example"}],
        )["example"]
        self.assertEqual(result["0.25"]["matched_targets"], 1)
        self.assertEqual(result["0.25"]["unmatched_predictions"], 1)
        self.assertEqual(result["0.25"]["annotated_recall"], 0.5)
        self.assertEqual(result["0.1"]["matched_targets"], 2)
        self.assertEqual(result["0.1"]["unmatched_predictions"], 1)
        self.assertNotIn("false_positive", result["0.1"])

    def test_camera_audit_keeps_distinct_identity_galleries_and_unknown_queries(self):
        rows = [
            {"panel": "enrollment", "cow": cow, "camera": camera}
            for camera in ("a", "b")
            for cow in (0, 1)
        ] + [
            {"panel": "test", "video": "example", "cow": cow, "camera": "a"}
            for cow in (0, 1, 7)
        ]
        vectors = np.asarray([[1, 0], [0, 1], [0, 1], [1, 0], [1, 0], [0, 1], [1, 1]])
        result = camera_audit(rows, vectors)["example"]
        self.assertEqual(result["same_camera"]["known_rank1"], 1.0)
        self.assertEqual(result["other_camera"]["known_rank1"], 0.0)
        for variant in result.values():
            self.assertEqual(variant["reference_identities"], 2)
            self.assertEqual(variant["known"], 2)
            self.assertEqual(variant["unknown"], 1)
            self.assertEqual(variant["unknown_false_accepts"], 0)


if __name__ == "__main__":
    unittest.main()
