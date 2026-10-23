from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("kornia")
pytest.importorskip("onnxruntime")


def test_the_coat_check_exports_with_the_same_matches_as_kornia(tmp_path: Path):
    weights = Path(torch.hub.get_dir()) / "checkpoints"
    if not (weights / "aliked-n16.pth").exists():
        pytest.skip("ALIKED's weights are not downloaded")
    from PIL import Image

    from reid.coat_export import export_coat_check

    rng = np.random.default_rng(0)
    coat = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    pictures = []
    # A wide picture, the same shifted, so there is something to match, and a
    # tall one, so both orientations go through the exported networks.
    for name, picture in (
        ("wide", coat),
        ("shifted", coat[6:, 10:]),
        ("tall", coat.transpose(1, 0, 2)),
    ):
        pictures.append(tmp_path / f"{name}.png")
        Image.fromarray(np.ascontiguousarray(picture)).save(pictures[-1])

    differences = export_coat_check(tmp_path / "coat", pictures, size=256)

    assert differences["keypoints"] < 1e-3
    assert differences["matches"] == 0
