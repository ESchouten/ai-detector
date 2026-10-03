"""Account for human effort without reading identity labels before selection."""

import json
import unittest
from collections import Counter

import numpy as np
from recognition_enrollment import PROTOCOL, enroll


class EnrollmentTest(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(PROTOCOL.read_text())
        quality = {"clipped": False, "minimum_side": 100, "overlap": 0.0}
        self.rows = [
            {**quality, "panel": "enrollment", "second": i * 5, "cow": cow}
            for cow in range(1, 7)
            for i in range(10)
        ]
        vectors = [np.eye(12)[row["cow"] - 1] for row in self.rows]
        self.rows.append({**quality, "panel": "development", "second": 330, "cow": 7})
        vectors.append(np.eye(12)[6])
        for offset, second in enumerate((345, 360, 375)):
            self.rows.append(
                {**quality, "panel": "development", "second": second, "cow": 1}
            )
            vectors.append(0.4 * np.eye(12)[0] + np.sqrt(0.84) * np.eye(12)[7 + offset])
        self.rows.append(
            {**quality, "panel": "development_later", "second": 930, "cow": 1}
        )
        vectors.append(np.eye(12)[11])
        self.vectors = np.stack(vectors)

    def test_unknown_and_over_cap_questions_count_without_enrolling_them(self):
        gallery, prompts = enroll(
            self.rows, self.vectors, list(range(60)), self.protocol
        )
        self.assertEqual(len(prompts), 4)
        self.assertEqual(
            Counter(p["outcome"] for p in prompts),
            {
                "reference confirmed": 2,
                "unknown remains unenrolled": 1,
                "known cow already at confirmation cap": 1,
            },
        )
        self.assertEqual(
            Counter(self.rows[i]["cow"] for i in gallery), {i: 10 for i in range(1, 7)}
        )
        self.assertEqual(set(gallery) - set(range(60)), {61, 62})
        self.assertTrue(all(330 <= p["second"] <= 629 for p in prompts))

    def test_first_choice_does_not_use_the_revealed_identity(self):
        _, original = enroll(self.rows, self.vectors, list(range(60)), self.protocol)
        changed = [dict(row) for row in self.rows]
        changed[60]["cow"] = 6
        _, altered = enroll(changed, self.vectors, list(range(60)), self.protocol)
        self.assertEqual(original[0]["row"], altered[0]["row"])
        self.assertNotEqual(original[0]["outcome"], altered[0]["outcome"])


if __name__ == "__main__":
    unittest.main()
