from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from reid.backbones import HALF, PRESETS, TorchEmbedder, _load_checkpoint, preset

torch = pytest.importorskip("torch")
timm = pytest.importorskip("timm")


def test_presets_and_timm_specs():
    assert preset("megadescriptor-l-384") is PRESETS["megadescriptor-l-384"]
    assert preset("timm:resnet50@256").model == "resnet50"
    assert preset("timm:resnet50@256").size == 256
    with pytest.raises(ValueError, match="Unknown model"):
        preset("nothing")


def _pictures(tmp_path: Path) -> list[Path]:
    paths = []
    for index, colour in enumerate(((200, 30, 30), (30, 200, 30), (30, 30, 200))):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (40, 24), colour).save(path)
        paths.append(path)
    return paths


def test_embeddings_are_normalised_rows_in_path_order(tmp_path: Path):
    network = timm.create_model("resnet18", pretrained=False, num_classes=0)
    embedder = TorchEmbedder("tiny", network, 32, HALF, batch_size=2, device="cpu")
    paths = _pictures(tmp_path)

    vectors = embedder.embed(paths)

    assert vectors.shape == (3, 512)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, rtol=1e-5)
    np.testing.assert_allclose(embedder.embed(paths[2:]), vectors[2:], atol=1e-5)


def test_grayscale_ignores_colour(tmp_path: Path):
    network = timm.create_model("resnet18", pretrained=False, num_classes=0)
    embedder = TorchEmbedder("tiny", network, 32, HALF, grayscale=True, device="cpu")
    red, gray = tmp_path / "red.png", tmp_path / "gray.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(red)
    Image.new("RGB", (8, 8)).convert("L").point(lambda _: 76).save(gray)

    vectors = embedder.embed([red, gray])

    np.testing.assert_allclose(vectors[0], vectors[1], atol=1e-5)


def test_checkpoint_weights_replace_the_network_weights(tmp_path: Path):
    source = timm.create_model("resnet18", pretrained=False, num_classes=0)
    path = tmp_path / "weights.pt"
    torch.save(
        {"state_dict": {f"module.{k}": v for k, v in source.state_dict().items()}}, path
    )
    target = timm.create_model("resnet18", pretrained=False, num_classes=0)

    _load_checkpoint(target, path)

    for name, tensor in source.state_dict().items():
        assert torch.equal(target.state_dict()[name], tensor)


def test_a_checkpoint_for_another_network_is_refused(tmp_path: Path):
    path = tmp_path / "weights.pt"
    torch.save({"unrelated.weight": torch.zeros(1)}, path)

    with pytest.raises(ValueError, match="no weights"):
        _load_checkpoint(timm.create_model("resnet18", pretrained=False), path)
