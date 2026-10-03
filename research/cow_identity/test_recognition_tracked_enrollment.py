"""Human confirmation cannot bypass identity, source-window or effort bounds."""

import unittest

import numpy as np
from recognition_tracked_enrollment import confirmed_arrays


class ConfirmedReferencesTest(unittest.TestCase):
    def setUp(self):
        self.rows = [{"panel": "enrollment", "cow": i} for i in (1, 2)]
        self.extra = [
            {"truth": 1},
            {"truth": 1},
            {"truth": 1},
            {"truth": None},
            {"truth": 7},
        ]
        self.archives = {
            "initial": ({"rows": self.rows}, np.eye(2)),
            "additional": ({"rows": self.extra}, np.ones((5, 2))),
        }
        self.references = [
            {"archive": "initial", "row": i, "cow": i + 1} for i in range(2)
        ]

    def test_unknown_unmatched_and_query_photos_cannot_enter_gallery(self):
        for index in (3, 4):
            refs = self.references + [{"archive": "additional", "row": index, "cow": 1}]
            with self.assertRaisesRegex(ValueError, "unknown or mislabeled"):
                confirmed_arrays(refs, self.archives, [1, 2])
        self.rows[0]["panel"] = "development_later"
        with self.assertRaisesRegex(ValueError, "early enrollment"):
            confirmed_arrays(self.references, self.archives, [1, 2])

    def test_two_new_references_are_allowed_but_third_and_duplicates_are_rejected(self):
        refs = self.references + [
            {"archive": "additional", "row": i, "cow": 1} for i in range(2)
        ]
        _, owners = confirmed_arrays(refs, self.archives, [1, 2])
        self.assertEqual(owners.tolist(), [1, 2, 1, 1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            confirmed_arrays(refs + [refs[-1]], self.archives, [1, 2])
        with self.assertRaisesRegex(ValueError, "reference budget"):
            confirmed_arrays(
                refs + [{"archive": "additional", "row": 2, "cow": 1}],
                self.archives,
                [1, 2],
            )


if __name__ == "__main__":
    unittest.main()
