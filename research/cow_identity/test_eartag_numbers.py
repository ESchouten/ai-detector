import unittest

from eartag_numbers import barcode_nl9, printed_nl9


class DutchNumberTest(unittest.TestCase):
    def test_both_published_examples_and_whitespace_layout(self):
        for value, expected in (
            ("NL 194 625 043", "194625043"),
            ("NL 1234\n5681 4", "123456814"),
        ):
            with self.subTest(value=value):
                self.assertEqual(printed_nl9(value), expected)
                for format_name in ("Code128", "ITF"):
                    self.assertEqual(
                        barcode_nl9("0" + expected, format_name, country="NL"),
                        expected,
                    )

    def test_every_single_digit_corruption_is_rejected_without_repair(self):
        original = "123456814"
        for position in range(9):
            for replacement in "0123456789":
                if original[position] == replacement:
                    continue
                damaged = original[:position] + replacement + original[position + 1 :]
                with self.subTest(damaged=damaged):
                    self.assertIsNone(printed_nl9("NL" + damaged))

    def test_partial_other_scheme_and_visual_substitutions_stay_unresolved(self):
        for value in (
            "5681",
            "NL 5681",
            "123456814",
            "NL 123456B14",
            "NL 1234568I4",
            "NL 1234-56814",
            "BE123456814",
            "NL130000000061",
            "NL0123456814",
        ):
            with self.subTest(value=value):
                self.assertIsNone(printed_nl9(value))
        self.assertIsNone(barcode_nl9("0123456814", "Code128", country=""))
        self.assertIsNone(barcode_nl9("0123456814", "QRCode", country="NL"))
        self.assertIsNone(barcode_nl9("123456814", "Code128", country="NL"))

    def test_checksum_is_not_proof_of_identity_or_correct_transcription(self):
        # Two compensating digit errors pass. Never equate a checksum with confidence.
        self.assertEqual(printed_nl9("NL124456714"), "124456714")
        self.assertNotEqual(printed_nl9("NL124456714"), printed_nl9("NL123456814"))


if __name__ == "__main__":
    unittest.main()
