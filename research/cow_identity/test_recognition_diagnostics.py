import numpy as np
import pytest
from recognition_diagnostics import foreground_bounds, staged_names
from recognition_temporal import temporal_names
from scoring import Scores


def test_foreground_bounds_preserve_coordinate_origin_and_exclusive_end():
    image = np.full((10, 20, 3), 127, dtype=np.uint8)
    image[2:8, 3:11] = 0
    assert foreground_bounds(image, [100, 200, 120, 210]) == [103, 202, 111, 208]
    assert foreground_bounds(np.full_like(image, 127), [100, 200, 120, 210]) == [
        100,
        200,
        120,
        210,
    ]
    with pytest.raises(ValueError, match="dimensions differ"):
        foreground_bounds(image, [0, 0, 10, 10])


def test_staged_confirmation_keeps_exact_temporal_collision_state():
    rows = [
        {"second": second, "track": track} for second in range(6) for track in (1, 2)
    ]
    predicted = np.array([1, 2] * 3 + [1, 1] * 3)
    scores = Scores(
        np.zeros(12),
        predicted,
        np.ones(12),
        np.ones(12),
        np.ones(12, dtype=bool),
        np.zeros(12),
    )
    stages = staged_names(rows, scores, 0.55, 0.2)
    np.testing.assert_array_equal(
        stages["three_observations_with_collision_rejection"],
        temporal_names(rows, scores, 0.55, 0.2, 0),
    )
    assert (stages["candidate_conflict_rejection_only"][6:] == 0).all()
