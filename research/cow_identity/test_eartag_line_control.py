import unittest

from eartag_line_control import inputs_without_text, line_totals


class TestOracleLines(unittest.TestCase):
    def test_geometry_input_never_carries_transcripts(self):
        source = {"id": "tag", "image": "tag.jpg"}
        manifest = {
            "rows": [{"id": "tag", "lines": [{"polygon": [1, 2], "text": "007"}]}]
        }
        self.assertEqual(
            inputs_without_text(manifest, [source]),
            [{**source, "lines": [{"index": 0, "polygon": [1, 2]}]}],
        )

    def test_rejected_and_missing_lines_keep_denominator_and_prevent_full_tag(self):
        truth = {"tag": [{"text": "007"}, {"text": "8-7"}]}
        rows = [
            {"id": "tag", "index": 0, "text": "007", "score": 0.94},
            {"id": "tag", "index": 1, "text": None, "score": None},
        ]
        result = line_totals(truth, rows, 0.95)
        self.assertEqual(
            (
                result["ground_truth_lines"],
                result["missed_or_rejected"],
                result["full_tag_exact"],
            ),
            (2, 2, 0),
        )

    def test_complete_multiline_tag_requires_literal_zeros_and_punctuation(self):
        truth = {"tag": [{"text": "007"}, {"text": "8-7"}]}
        rows = [
            {"id": "tag", "index": 0, "text": "7", "score": 0.999},
            {"id": "tag", "index": 1, "text": "8.7", "score": 0.999},
        ]
        self.assertEqual(line_totals(truth, rows, 0.95)["wrong_text"], 2)
        rows[0]["text"], rows[1]["text"] = "007", "8-7"
        self.assertEqual(line_totals(truth, rows, 0.95)["full_tag_exact"], 1)


if __name__ == "__main__":
    unittest.main()
