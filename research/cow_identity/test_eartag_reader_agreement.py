import unittest

from eartag_ocr import score_image
from eartag_reader_agreement import agreed_predictions


class ReaderAgreementTest(unittest.TestCase):
    def test_literal_agreement_never_corrects_digits_or_country(self):
        first = [
            {"text": text, "score": score, "polygon": [index]}
            for index, (text, score) in enumerate(
                [
                    ("00123", 0.99),
                    ("123", 0.99),
                    ("NL 123", 0.99),
                    ("42", 0.94),
                    (" ", 1),
                ]
            )
        ]
        second = [
            {"text": text, "index": index, "polygon": [index]}
            for index, text in enumerate(["123", " 123 ", "NL123", "42", " "])
        ]
        self.assertEqual(agreed_predictions(first, second), [first[1]])
        second[0]["polygon"] = [99]
        with self.assertRaisesRegex(ValueError, "same indexed polygon"):
            agreed_predictions(first, second)

    def test_rejection_preserves_full_truth_denominator_and_accepted_extras(self):
        polygons = [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10]] for x in (0, 20)]
        first = [
            {"text": "1", "score": 0.99, "polygon": polygon} for polygon in polygons
        ]
        second = [
            {"text": text, "index": i, "polygon": polygons[i]}
            for i, text in enumerate(["2", "1"])
        ]
        result = score_image(
            [{"text": "1", "polygon": polygons[0]}], agreed_predictions(first, second)
        )
        self.assertEqual(result["missed_lines"], 1)
        self.assertEqual(result["unmatched_texts"], 1)
        self.assertEqual(result["correct_text"], 0)


if __name__ == "__main__":
    unittest.main()
