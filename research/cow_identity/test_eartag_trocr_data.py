import unittest

from eartag_trocr_data import crop_entries, training_rows


class TestTrainingSeparation(unittest.TestCase):
    def test_entire_pilot_groups_and_all_nontraining_splits_are_excluded(self):
        rows = [
            {"id": "pilot", "group": "same", "split": "development"},
            {"id": "otherphoto", "group": "same", "split": "development"},
            {"id": "train", "group": "train", "split": "development"},
            {"id": "calibration", "group": "cal", "split": "calibration"},
            {"id": "reserved", "group": "test", "split": "reserved"},
        ]
        self.assertEqual(training_rows({"rows": rows}, ["pilot"]), [rows[2]])

    def test_train_literal_labels_preserved_but_inference_entries_have_no_text(self):
        lines = [{"text": "0024", "polygon": [0, 0, 10, 0, 10, 10, 0, 10]}]
        self.assertEqual(crop_entries({"id": "tag"}, lines, True)[0]["text"], "0024")
        self.assertNotIn("text", crop_entries({"id": "tag"}, lines, False)[0])


if __name__ == "__main__":
    unittest.main()
