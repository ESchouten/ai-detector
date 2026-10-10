import numpy as np

from parts_from_run import members


def test_a_run_s_kept_descriptions_come_apart_into_its_networks():
    unit = np.ones((2, 256), dtype=np.float16) / 16
    saved = {
        # Two cattle networks, each scaled down by the root of two, then the second kind.
        "parts": np.array([512, 3]),
        "photographs": np.concatenate([unit / np.sqrt(2), unit / np.sqrt(2), np.eye(2, 3)], 1),
        "crops": np.concatenate([unit / np.sqrt(2), unit / np.sqrt(2), np.eye(2, 3)], 1),
    }

    names, photographs, crops = zip(*members(saved), strict=True)

    assert names == ("cattle-s0", "cattle-s1", "animal-s2")
    # Each network's description is a whole one again.
    assert np.allclose((photographs[0] ** 2).sum(1), 1, atol=1e-2)
    assert crops[2].shape == (2, 3)
