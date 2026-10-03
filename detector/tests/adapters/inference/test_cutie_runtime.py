import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import numpy as np
import pytest

from aidetector.adapters.inference.cutie_runtime import (
    MAX_OBJECT_ID,
    CutieUnavailable,
    mask_evidence,
    open_cutie,
)


def test_import_does_not_load_optional_model_dependencies():
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import aidetector.adapters.inference.cutie_runtime; "
            "assert not {'torch', 'cutie', 'hydra', 'omegaconf'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def test_missing_or_incompatible_sdk_is_reported_before_model_loading(monkeypatch):
    def missing(_name):
        raise PackageNotFoundError("cutie")

    for installed_version in (missing, lambda _name: "1.0.0"):
        monkeypatch.setattr(
            "aidetector.adapters.inference.cutie_runtime.version", installed_version
        )
        with (
            pytest.raises(CutieUnavailable, match=r"Cutie 1\.0\.0\+aidetector\.2"),
            open_cutie(Path("not-loaded.pth"), "cpu"),
        ):
            pytest.fail("An incompatible SDK must not run")


def test_mask_quality_follows_current_channels_not_stable_id_order():
    mask = np.array([[42, 7], [0, 42]], dtype=np.int64)
    probabilities = np.zeros((4, 2, 2), dtype=np.float32)
    probabilities[1] = [[0.8, 0.1], [0.0, 0.6]]
    probabilities[2] = [[0.1, 0.9], [0.0, 0.1]]
    evidence = {
        item.object_id: item
        for item in mask_evidence(mask, probabilities, {7: 2, 42: 1, 105: 3})
    }
    assert evidence[42].area == 2
    assert evidence[42].mean_probability == pytest.approx(0.7)
    assert evidence[42].p10_probability == pytest.approx(0.62)
    assert evidence[7].mean_probability == pytest.approx(0.9)
    assert evidence[105].area == 0
    assert evidence[105].mean_probability is None
    assert evidence[105].p10_probability is None

    # Deleting an object compacts SDK channels, without renaming stable IDs.
    compacted = mask_evidence(
        np.array([[7]], dtype=np.int64),
        np.array([[[0.2]], [[0.8]]], dtype=np.float32),
        {7: 1},
    )
    assert compacted[0].object_id == 7
    assert compacted[0].mean_probability == pytest.approx(0.8)


def test_unknown_mask_ids_and_nonfinite_quality_cannot_escape_sdk_boundary():
    mask = np.array([[42]], dtype=np.int64)
    with pytest.raises(ValueError, match="correspondence"):
        mask_evidence(mask, np.zeros((2, 1, 1), dtype=np.float32), {7: 1})
    with pytest.raises(ValueError, match="correspondence"):
        mask_evidence(mask, np.full((2, 1, 1), np.nan, dtype=np.float32), {42: 1})


@pytest.fixture
def local_cutie_weights():
    path = os.environ.get("AIDETECTOR_TEST_CUTIE_WEIGHTS")
    if not path:
        pytest.skip("Optional Cutie contract requires explicit local pinned weights")
    return Path(path)


def test_real_cpu_sdk_lifecycle_and_boundary(local_cutie_weights, tmp_path):
    """Opt-in public SDK contract: no model download or accelerator required."""
    import torch

    previous_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        _exercise_real_runtime(local_cutie_weights)
        damaged = tmp_path / "damaged.pth"
        damaged.write_bytes(b"not the pinned checkpoint")
        with pytest.raises(ValueError, match="SHA-256"), open_cutie(damaged, "cpu"):
            pytest.fail("Invalid weights must not construct a running model")
    finally:
        torch.set_num_threads(previous_threads)


def _exercise_real_runtime(weights):
    image = np.zeros((128, 192, 3), dtype=np.uint8)
    image[15:110, 15:175] = (90, 150, 210)
    seed = np.zeros(image.shape[:2], dtype=np.int64)
    seed[20:70, 20:60] = 7
    seed[20:70, 75:115] = 42
    seed[20:70, 130:170] = 99
    with open_cutie(weights, "cpu") as runtime:
        assert runtime.device == "cpu"
        empty = runtime.step(image)
        assert not empty.mask.any() and empty.objects == ()
        _reject_invalid_seeds(runtime, image, seed)
        initial = runtime.step(image, mask=seed, object_ids=(7, 42, 99))
        assert runtime.object_ids == (7, 42, 99)
        assert np.array_equal(initial.mask, seed)
        assert not initial.mask.flags.writeable
        runtime.retire((42,))
        assert runtime.object_ids == (7, 99)
        followup = runtime.step(image)
        assert {item.object_id for item in followup.objects} == {7, 99}
        assert 42 not in np.unique(followup.mask)
        added = np.where(seed == 42, 105, 0).astype(np.int64)
        inserted = runtime.step(image, mask=added, object_ids=(105,))
        assert runtime.object_ids == (7, 99, 105)
        assert np.all(inserted.mask[added == 105] == 105)
        assert {item.object_id for item in inserted.objects} == {7, 99, 105}
        assert followup.mask.shape == image.shape[:2]
        assert followup.mask.dtype == np.int64
        with pytest.raises(ValueError, match="geometry"):
            runtime.step(image[:64])
        runtime.retire(runtime.object_ids)
        assert runtime.object_ids == ()
        assert not runtime.step(image[:64]).mask.any()
        new_seed = np.full((64, 192), 211, dtype=np.int64)
        assert runtime.step(image[:64], mask=new_seed, object_ids=(211,)).objects
        runtime.reset()
        assert runtime.object_ids == ()
        assert not runtime.step(image).mask.any()
        runtime.reset()
        camera_frame = np.zeros((512, 640, 3), dtype=np.uint8)
        camera_seed = np.zeros((512, 640), dtype=np.int64)
        camera_seed[80:430, 90:540] = MAX_OBJECT_ID
        restored = runtime.step(
            camera_frame, mask=camera_seed, object_ids=(MAX_OBJECT_ID,)
        )
        assert restored.mask.shape == (512, 640)
        assert restored.mask.dtype == np.int64
        assert set(np.unique(restored.mask)) == {0, MAX_OBJECT_ID}
        assert restored.objects[0].object_id == MAX_OBJECT_ID
        assert restored.objects[0].area == np.count_nonzero(restored.mask)
    runtime.close()  # Repeated cleanup is safe after a context exits.
    with pytest.raises(RuntimeError, match="closed"):
        runtime.step(image)


def _reject_invalid_seeds(runtime, image, seed):
    for mask, ids, message in (
        (None, (7,), "same-frame"),
        (seed, (7, 42), "exactly"),
        (seed, (7, 7, 42), "distinct NEW"),
        (seed, (MAX_OBJECT_ID + 1,), "distinct NEW"),
        (seed, tuple(range(1, 10)), "eight"),
    ):
        with pytest.raises(ValueError, match=message):
            runtime.step(image, mask=mask, object_ids=ids)
        assert runtime.object_ids == ()
