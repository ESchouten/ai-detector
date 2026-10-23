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
