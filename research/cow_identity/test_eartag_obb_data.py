"""Polygon serialization keeps tilt, excludes transcripts and rejects silent clipping."""

import numpy as np
import pytest
from eartag_obb_data import normalized_label


def test_original_tilted_polygon_roundtrip_without_axis_aligned_conversion():
    original = [10, 10, 60, 20, 55, 40, 5, 30]
    label = normalized_label(original, 80, 50)
    assert label.split()[0] == "0"
    restored = np.asarray(label.split()[1:], float).reshape(4, 2) * [80, 50]
    np.testing.assert_allclose(restored.ravel(), original, rtol=0, atol=1e-8)


def test_invalid_polygon_is_not_clipped_into_a_valid_training_label():
    with pytest.raises(ValueError, match="never silently clip"):
        normalized_label([-1, 0, 10, 0, 10, 5, 0, 5], 20, 20)
