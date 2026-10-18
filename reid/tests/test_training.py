from pathlib import Path

import numpy as np
import pytest

from reid.backbones import build
from reid.training import TrainOptions, batches, train

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
    embedder = build("timm:resnet18@32", checkpoint=out, device="cpu")
    vectors = embedder.embed([crop.path for crop in herd[:3]])
    assert vectors.shape == (3, 512)
    tuned = build("timm:resnet18@32", checkpoint=out, device="cpu").network.state_dict()
    original = torch.load(start)
    assert not torch.equal(tuned["conv1.weight"], original["conv1.weight"])
