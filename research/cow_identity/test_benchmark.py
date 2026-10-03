import tempfile
import unittest
from pathlib import Path

import numpy as np
from ablation import whitening
from benchmark import PROTOCOL, cache_key, prepare
from PIL import Image
from scoring import calibrate, metrics, score


class BenchmarkTest(unittest.TestCase):
    def test_whitening_retains_directions_absent_from_the_gallery(self):
        gallery = np.array(
            [[1.0, 0.1, 0.0], [1.0, -0.1, 0.0], [0.1, 1.0, 0.0], [-0.1, 1.0, 0.0]]
        )
        transform = whitening(gallery, np.array(["a", "a", "b", "b"]))
        np.testing.assert_allclose(
            transform(np.array([[0.0, 0.0, 1.0]])), [[0.0, 0.0, 1.0]]
        )

    def test_runner_up_is_another_cow_not_another_reference(self):
        result = score(
            np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
            np.array(["a", "a", "b"]),
            np.array([[1.0, 0.0]]),
            np.array(["a"]),
            np.array(["2"]),
        )
        self.assertEqual(result.predicted.tolist(), ["a"])
        self.assertEqual(result.margin.tolist(), [1.0])

    def test_calibration_rejects_lookalike_unknown(self):
        gallery = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        result = score(
            gallery,
            np.array(["a", "b"]),
            np.array([[1.0, 0.0, 0.0], [0.8, 0.1, 0.6]]),
            np.array(["a", "unknown"]),
            np.array(["2", "2"]),
        )
        threshold, margin = calibrate(result)
        measured = metrics(result, threshold, margin)
        self.assertEqual(measured["correct_accepts"], 1)
        self.assertEqual(measured["unknown_false_accepts"], 0)

    def test_unknown_accepts_reduce_precision(self):
        result = score(
            np.eye(2),
            np.array(["a", "b"]),
            np.eye(2),
            np.array(["a", "unknown"]),
            np.array(["2", "2"]),
        )
        self.assertEqual(metrics(result, 0.0, 0.0)["accepted_precision"], 0.5)

    def test_image_and_encoder_changes_invalidate_cache(self):
        key = cache_key("image-a", {"weights": "model-a", "size": 224})
        self.assertNotEqual(
            key, cache_key("image-b", {"weights": "model-a", "size": 224})
        )
        self.assertNotEqual(
            key, cache_key("image-a", {"weights": "model-a", "size": 336})
        )
        self.assertNotEqual(
            key, cache_key("image-a", {"weights": "model-b", "size": 224})
        )

    def test_manifest_withholds_unknowns_and_separates_cows_and_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for day_index, day in enumerate(
                (PROTOCOL["gallery_day"], PROTOCOL["query_day"])
            ):
                for cow in range(15):
                    directory = root / day / f"{cow:03d}"
                    directory.mkdir(parents=True)
                    for camera in range(1, 4):
                        Image.new(
                            "RGB", (10, 10), (day_index * 100, cow * 15, camera * 50)
                        ).save(directory / f"00001_{camera}.jpg")
            manifest = prepare(root)
            splits = {
                name: set(group["known"] + group["unknown"])
                for name, group in manifest["identities"].items()
            }
            self.assertFalse(splits["calibration"] & splits["test"])
            for record in manifest["images"]:
                group = manifest["identities"][record["split"]]
                if record["role"] == "gallery":
                    self.assertNotIn(record["identity"], group["unknown"])
                    self.assertTrue(record["path"].startswith(PROTOCOL["gallery_day"]))
                else:
                    self.assertTrue(record["path"].startswith(PROTOCOL["query_day"]))


if __name__ == "__main__":
    unittest.main()
