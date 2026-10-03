import importlib.util
import unittest

from eartag_ocr import score_image


def line(text, x=0, score=1.0):
    return {
        "text": text,
        "polygon": [x, 0, x + 10, 0, x + 10, 10, x, 10],
        "score": score,
    }


@unittest.skipUnless(
    importlib.util.find_spec("scipy"), "Use the isolated pinned OCR environment"
)
class TestOcrScore(unittest.TestCase):
    def test_leading_zeros_and_punctuation_are_not_normalized(self):
        result = score_image(
            [line("0024"), line("10-21", 20)], [line("24"), line("10.21", 20)]
        )
        self.assertEqual(result["correct_text"], 0)
        self.assertEqual(result["wrong_text"], 2)
        self.assertFalse(result["full_tag_exact"])

    def test_multiline_order_is_irrelevant_but_all_lines_and_extras_count(self):
        truth = [line(" 49 "), line("160239", 20)]
        self.assertTrue(
            score_image(truth, [line("160239", 20), line("49")])["full_tag_exact"]
        )
        result = score_image(
            truth, [line("160239", 20), line("49"), line("spurious", 40)]
        )
        self.assertEqual(result["correct_text"], 2)
        self.assertEqual(result["unmatched_texts"], 1)
        self.assertFalse(result["full_tag_exact"])

    def test_matching_is_one_to_one_and_confidence_rejection_keeps_miss(self):
        result = score_image([line("0024")], [line("0024"), line("0024")])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["unmatched_texts"], 1)
        result = score_image([line("0024")], [line("0024", score=0.94)], 0.95)
        self.assertEqual(result["ground_truth_lines"], 1)
        self.assertEqual(result["missed_lines"], 1)
        self.assertEqual(result["predictions"], 0)

    def test_invalid_polygons_and_unusual_truth_are_retained_not_dropped(self):
        bad = {"text": "###", "polygon": [0, 0, 10, 10, 0, 10, 10, 0]}
        result = score_image([bad], [line("###")])
        self.assertEqual(result["ground_truth_lines"], 1)
        self.assertEqual(result["missed_lines"], 1)
        self.assertEqual(result["unmatched_texts"], 1)
        self.assertEqual(result["invalid_truth_polygons"], [0])
        self.assertEqual(result["nonstandard_truth_strings"], [0])


if __name__ == "__main__":
    unittest.main()
