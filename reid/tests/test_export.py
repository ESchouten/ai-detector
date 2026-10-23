from pathlib import Path

import pytest

from reid.backbones import HALF
from reid.export import export_network

timm = pytest.importorskip("timm")
onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")


def test_exported_model_embeds_like_the_benchmark(tmp_path: Path):
    network = timm.create_model("resnet18", pretrained=False, num_classes=0)
    out = tmp_path / "model.onnx"

    difference = export_network(network, 32, HALF, out, "resnet18 test")

    assert difference < 1e-4
    model = onnx.load(str(out))
    assert {prop.key: prop.value for prop in model.metadata_props} == {
        "mean": "0.5,0.5,0.5",
        "std": "0.5,0.5,0.5",
        "description": "resnet18 test",
    }
    session = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    [images] = session.get_inputs()
    assert (images.name, images.shape[1:]) == ("images", [3, 32, 32])


class GeM(__import__("torch").nn.Module):
    """MiewID's pooling, which takes its kernel from the size of the feature map."""

    def __init__(self, p: float = 3, eps: float = 1e-6):
        import torch

        super().__init__()
        self.p = torch.nn.Parameter(torch.ones(1) * p)
        self.eps = eps

    def forward(self, x):
        import torch.nn.functional as F

        return F.avg_pool2d(
            x.clamp(min=self.eps).pow(self.p), (x.size(-2), x.size(-1))
        ).pow(1.0 / self.p)


def test_pooling_sized_from_the_feature_map_is_exported(tmp_path: Path):
    import torch

    network = torch.nn.Sequential(
        timm.create_model("resnet18", pretrained=False, num_classes=0, global_pool=""),
        GeM(),
    )

    assert export_network(network, 64, HALF, tmp_path / "model.onnx", "gem") < 1e-4
