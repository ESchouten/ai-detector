import unittest

from eartag_work_numbers import work_number


class WorkNumberTest(unittest.TestCase):
    def test_complete_readings_preserve_leading_zeros_without_country_or_checksum(self):
        for text, expected in (("0042", "0042"), (" 5678\n", "5678"), ("0000", "0000")):
            with self.subTest(text=text):
                self.assertEqual(work_number(text), expected)

    def test_other_text_is_not_repaired_truncated_or_joined(self):
        for text in (
            "",
            "42",
            "12345",
            "NL123456789",
            "NL 0042",
            "00\n42",
            "00 42",
            "00-42",
            "OO42",
            "004Z",
            "００４２",
            "٠٠٤٢",
            "0042 / 5678",
        ):
            with self.subTest(text=text):
                self.assertIsNone(work_number(text))

    def test_syntax_cannot_certify_that_a_reading_is_a_work_number(self):
        self.assertEqual(work_number("2026"), "2026")
        # The tag-region/ownership evidence, not this parser, must exclude dates.


if __name__ == "__main__":
    unittest.main()
