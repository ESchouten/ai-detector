import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from reid.backbones import IMAGENET, PRESETS, build
from reid.training import TrainOptions, _augmented, batches, hide, train

torch = pytest.importorskip("torch")
timm = pytest.importorskip("timm")


def test_batches_hold_p_animals_with_k_crops_each(herd):
    options = TrainOptions(identities_per_batch=4, crops_per_identity=3)

    epoch = list(batches(herd, options, np.random.default_rng(0)))

    assert len(epoch) == 2
    for batch in epoch:
        identities = [herd[i].identity for i in batch]
        assert len(set(identities)) == 4
        assert all(identities.count(name) == 3 for name in set(identities))


def test_batches_never_mix_farms_and_keep_small_farms(herd):
    farms = ["north" if int(crop.identity[3:]) < 5 else "south" for crop in herd]

    epoch = list(
        batches(
            herd,
            TrainOptions(identities_per_batch=4, crops_per_identity=2),
            np.random.default_rng(0),
            farms,
        )
    )

    assert len(epoch) == 2
    sizes = sorted(len({herd[i].identity for i in batch}) for batch in epoch)
    assert sizes == [3, 4]
    for batch in epoch:
        assert len({farms[i] for i in batch}) == 1


def test_training_saves_a_backbone_the_benchmark_can_load(herd, tmp_path: Path):
    start = tmp_path / "start.pt"
    torch.save(
        timm.create_model("resnet18", pretrained=False, num_classes=0).state_dict(),
        start,
    )
    out = tmp_path / "tuned.safetensors"

    train(
        herd,
        "timm:resnet18@32",
        out,
        TrainOptions(epochs=2, identities_per_batch=4, crops_per_identity=2),
        checkpoint=start,
        device="cpu",
    )

    assert out.exists() and out.with_suffix(".json").exists()
    record = json.loads(out.with_suffix(".json").read_text())
    assert record["epochs"] == 2 and len(record["loss"]) == 2
    assert not out.with_name(out.name + ".partial").exists()
    embedder = build("timm:resnet18@32", checkpoint=out, device="cpu")
    vectors = embedder.embed([crop.path for crop in herd[:3]])
    assert vectors.shape == (3, 512)
    tuned = build("timm:resnet18@32", checkpoint=out, device="cpu").network.state_dict()
    original = torch.load(start)
    assert not torch.equal(tuned["conv1.weight"], original["conv1.weight"])


def test_miewid_loaded_through_transformers_can_be_fine_tuned(
    herd, tmp_path: Path, monkeypatch
):
    transformers = pytest.importorskip("transformers")

    def published(model, **options):
        torch.manual_seed(0)
        return timm.create_model("resnet18", pretrained=False, num_classes=0)

    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", published)
    monkeypatch.setitem(
        PRESETS, "miewid-msv3", replace(PRESETS["miewid-msv3"], size=32)
    )
    out = tmp_path / "miewid-cows.safetensors"

    train(
        herd,
        "miewid-msv3",
        out,
        TrainOptions(epochs=1, identities_per_batch=4, crops_per_identity=2, chunk=3),
        device="cpu",
    )

    tuned = build("miewid-msv3", checkpoint=out, device="cpu").network.state_dict()
    original = published("conservationxlabs/miewid-msv3").state_dict()
    assert not torch.equal(tuned["conv1.weight"], original["conv1.weight"])


def test_gray_chance_turns_that_share_of_pictures_gray(tmp_path: Path):
    from PIL import Image

    path = tmp_path / "red-cow.png"
    Image.new("RGB", (40, 30), (200, 40, 30)).save(path)
    mean, std = (np.asarray(value).reshape(3, 1, 1) for value in IMAGENET)

    def gray(chance: float, seed: int) -> bool:
        pixels = _augmented(path, 16, IMAGENET, chance, np.random.default_rng(seed))
        raw = pixels * std + mean
        return bool(np.allclose(raw[0], raw[1], atol=1e-5))

    assert not any(gray(0.0, seed) for seed in range(20))
    assert all(gray(1.0, seed) for seed in range(20))
    assert 5 < sum(gray(0.5, seed) for seed in range(40)) < 35


def test_hidden_pictures_show_only_part_of_the_cow():
    from PIL import Image

    coat = np.random.default_rng(0).integers(0, 256, (30, 40, 3), np.uint8)
    picture = Image.fromarray(coat)
    hidden = [
        np.asarray(hide(picture, np.random.default_rng(seed))) for seed in range(30)
    ]

    assert all(pixels.shape == coat.shape for pixels in hidden)
    assert not any(np.array_equal(pixels, coat) for pixels in hidden)
    # Rails and patches are painted in a flat gray; a band shows the coat alone.
    painted = [
        ((pixels[..., 0] == pixels[..., 1]) & (pixels[..., 1] == pixels[..., 2])).mean()
        > 0.03
        for pixels in hidden
    ]
    assert any(painted)
    assert not all(painted)


def test_partial_hides_part_of_that_share_of_pictures(tmp_path: Path):
    from PIL import Image

    path = tmp_path / "coat.png"
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(0, 256, (30, 40, 3), np.uint8)).save(path)
    mean, std = (np.asarray(value).reshape(3, 1, 1) for value in IMAGENET)

    def painted(partial: float, seed: int) -> bool:
        raw = _augmented(path, 16, IMAGENET, 0.0, np.random.default_rng(seed), partial)
        raw = raw * std + mean
        flat = np.isclose(raw[0], raw[1], atol=1e-4) & np.isclose(
            raw[1], raw[2], atol=1e-4
        )
        return bool(flat.mean() > 0.03)

    assert not any(painted(0.0, seed) for seed in range(20))
    assert 5 < sum(painted(1.0, seed) for seed in range(40)) < 40
