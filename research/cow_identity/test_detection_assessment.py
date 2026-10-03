import json
import math
import unittest

import numpy as np
from detection_assessment import PROTOCOL, score
from detection_data import enclosing_box
from detection_errors import category, overlaps
from detection_nms import changed_matches, suppress
from detection_overlap import overlap_scores
from detection_tracking import summarize

from aidetector.domain.models import BoundingBox


class LocalizationAssessmentTest(unittest.TestCase):
    def test_directional_overlap_distinguishes_complete_crop_from_contained_part(self):
        whole = BoundingBox(1, 1, 101, 101)
        part = BoundingBox(1, 1, 21, 21)
        self.assertEqual(
            overlap_scores(whole, [whole, part]), {"symmetric": 1.0, "own": 0.04}
        )
        self.assertEqual(
            overlap_scores(part, [whole, part]), {"symmetric": 1.0, "own": 1.0}
        )

    def test_error_audit_distinguishes_duplicate_merged_and_partial_boxes(self):
        truth = [
            {"cow": 1, "box": [0, 0, 10, 10]},
            {"cow": 2, "box": [15, 0, 25, 10]},
        ]
        for box, expected in (
            (BoundingBox(0, 0, 10, 10), "duplicate_like"),
            (BoundingBox(0, 0, 25, 10), "spans_multiple_cows"),
            (BoundingBox(0, 0, 4, 4), "partial_or_loose"),
        ):
            self.assertEqual(category(overlaps(box, truth)), expected)

    def test_stricter_nms_reports_when_it_removes_a_real_adjacent_cow(self):
        boxes = [[0, 0, 10, 10], [3, 0, 13, 10]]
        frames = [{"truth": [{"cow": i, "box": box} for i, box in enumerate(boxes)]}]
        predictions = [{"boxes": boxes, "confidence": [0.9, 0.8]}]
        filtered = suppress(predictions, 0.45)
        result = changed_matches(frames, predictions, filtered, 0.4)
        self.assertEqual(result["newly_missed_annotations"], 1)
        self.assertEqual(score(frames, filtered, 0.4)["recall"], 0.5)

    def test_duplicate_suppression_does_not_count_a_lost_real_cow(self):
        box = [0, 0, 10, 10]
        frames = [{"truth": [{"cow": 1, "box": box}]}]
        predictions = [{"boxes": [box, box], "confidence": [0.9, 0.8]}]
        filtered = suppress(predictions, 0.45)
        self.assertEqual(
            changed_matches(frames, predictions, filtered, 0.4)[
                "newly_missed_annotations"
            ],
            0,
        )
        self.assertEqual(score(frames, filtered, 0.4)["precision"], 1.0)

    def test_publisher_radians_rotate_about_box_center_before_clipping(self):
        np.testing.assert_allclose(
            enclosing_box([20, 30, 40, 10, math.pi / 2], 100, 100),
            [35, 15, 45, 55],
        )
        self.assertEqual(enclosing_box([-5, -5, 20, 20, 0], 10, 10), (0, 0, 10, 10))

    def test_track_identity_metric_penalizes_fragmentation_despite_perfect_boxes(self):
        timeline = [
            {
                "second": second,
                "truth": [{"cow": 1, "box": [0, 0, 10, 10]}],
                "boxes": [{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "track_id": track}],
            }
            for second, track in ((330, 1), (331, 2))
        ]
        result = summarize({"timeline": timeline})
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["global_identity_f1"], 0.5)
        self.assertEqual(result["counts"]["cow_track_switches"], 1)

    def test_scoring_filters_confidence_and_never_double_counts_one_cow(self):
        frames = [
            {
                "truth": [
                    {"cow": 1, "box": [0, 0, 10, 10]},
                    {"cow": 7, "box": [20, 0, 30, 10]},
                ]
            }
        ]
        predictions = [
            {
                "boxes": [[0, 0, 10, 10], [0, 0, 10, 10], [20, 0, 30, 10]],
                "confidence": [0.9, 0.8, 0.1],
            }
        ]
        result = score(frames, predictions, 0.25)
        self.assertEqual(result["true_positive"], 1)
        self.assertEqual(result["false_positive"], 1)
        self.assertEqual(result["false_negative"], 1)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)

    def test_training_and_calibration_cannot_include_reserved_queries(self):
        protocol = json.loads(PROTOCOL.read_text())
        sets = {
            name: set(range(row["start"], row["stop"], row["step"]))
            for name, row in protocol["splits"].items()
        }
        for fit in ("train", "calibration"):
            for query in ("development", "development_later", "final", "reserve"):
                self.assertFalse(sets[fit] & sets[query], (fit, query))
        self.assertLess(max(sets["train"]), min(sets["calibration"]))
        self.assertEqual(len(sets["train"]), 150)
        self.assertEqual(len(sets["calibration"]), 90)


if __name__ == "__main__":
    unittest.main()
