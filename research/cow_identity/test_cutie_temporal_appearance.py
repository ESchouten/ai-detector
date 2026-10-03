import numpy as np
from cutie_temporal_appearance import smooth_vectors


def test_pooling_is_causal_per_original_slot_and_resets_missing_slots_and_frames():
    features = {
        "rows": [{"track_id": track} for track in [0, 1, 0, 1, 0, 1, 0]],
        "frames": [
            {"second": 330, "rows": [0, 1]},
            {"second": 331, "rows": [2, 3]},
            {"second": 332, "rows": [4]},
            {"second": 333, "rows": [5]},
            {"second": 930, "rows": [6]},
        ],
    }
    vectors = np.array(
        [[1, 0], [0, 1], [0, 1], [1, 0], [1, 0], [1, 0], [0, 1]], dtype=np.float32
    )
    actual = smooth_vectors(features, vectors, 0.5)
    np.testing.assert_array_equal(actual[:2], vectors[:2])
    np.testing.assert_allclose(actual[2:4], np.full((2, 2), 1 / np.sqrt(2)), atol=1e-6)
    np.testing.assert_array_equal(actual[5:], vectors[5:])
    changed_future = vectors.copy()
    changed_future[4:] *= -1
    np.testing.assert_array_equal(
        smooth_vectors(features, changed_future, 0.5)[:4], actual[:4]
    )


def test_raw_control_keeps_normalized_vectors():
    features = {
        "rows": [{"track_id": 3}, {"track_id": 3}],
        "frames": [{"second": 1, "rows": [0]}, {"second": 2, "rows": [1]}],
    }
    vectors = np.array([[1.0, 0], [0, 1.0]], dtype=np.float32)
    np.testing.assert_array_equal(smooth_vectors(features, vectors, 1), vectors)
