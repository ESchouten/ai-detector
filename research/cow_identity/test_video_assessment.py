import unittest

from video_assessment import VideoMetrics, pair_boxes

from aidetector.domain.models import BoundingBox, IdentityMatch


def box(x, *, name=None, track=None):
    return BoundingBox(
        x,
        0,
        x + 10,
        10,
        "cow",
        1.0,
        track,
        IdentityMatch(f"{name:032x}") if name is not None else IdentityMatch(),
    )


class VideoAssessmentTest(unittest.TestCase):
    def test_matching_is_one_to_one_with_duplicates_and_missing_boxes(self):
        truth = [{"cow": 1, "box": [0, 0, 10, 10]}, {"cow": 2, "box": [20, 0, 30, 10]}]
        pairs = pair_boxes([box(0), box(0), box(20), box(50)], truth)
        self.assertEqual(set(pairs.values()), {0, 1})
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[2], 1)
        self.assertEqual(pair_boxes([box(0)], truth), {0: 0})
        self.assertEqual(pair_boxes([], truth), {})

    def test_visible_coverage_and_unknown_names_are_not_closed_set_accuracy(self):
        metrics = VideoMetrics()
        truth = [
            {"cow": cow, "box": [x, 0, x + 10, 10]}
            for cow, x in ((1, 0), (2, 20), (7, 40), (8, 60), (3, 100))
        ]
        boxes = [
            box(0, name=1, track=10),
            box(20, name=1, track=20),
            box(40, name=2, track=30),
            box(60),
            box(80, name=3),
        ]
        metrics.add(330, boxes, truth, [True, True, True, False, True])
        self.assertEqual(metrics.counts["correct_name"], 1)
        self.assertEqual(metrics.counts["wrong_name"], 1)
        self.assertEqual(metrics.counts["unknown_named"], 1)
        self.assertEqual(metrics.counts["unknown_rejected"], 1)
        self.assertEqual(metrics.counts["unmatched_named"], 1)
        self.assertEqual(metrics.counts["visible_known"], 3)
        self.assertEqual(metrics.counts["visible_unknown"], 2)
        self.assertEqual(metrics.counts["missed_annotations"], 1)
        metrics.add(331, [box(0, name=2, track=20)], truth, [True])
        self.assertEqual(metrics.counts["cow_name_switches"], 1)
        self.assertEqual(metrics.counts["cow_track_switches"], 1)
        self.assertEqual(metrics.counts["track_cow_switches"], 1)
        metrics.add(340, [box(0, name=1, track=10)], truth, [True])
        self.assertEqual(metrics.counts["cow_name_switches"], 1)


if __name__ == "__main__":
    unittest.main()
