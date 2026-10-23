"""Write an embedding network as the ONNX model ai-detector's `individuals` takes.

The model's input is `images`, float32 RGB pictures as N×3×H×W at the
network's square size, normalised with the `mean` and `std` stored in its
metadata; its output is `embeddings`, one row per picture. The detector
squares and normalises crops the same way the benchmark does.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from reid.backbones import features, load_network, preset

if TYPE_CHECKING:
    import torch


def _embeddings(network: torch.nn.Module) -> torch.nn.Module:
    import torch

    class Embeddings(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = network

        def forward(self, images: torch.Tensor) -> torch.Tensor:
            return features(self.network(images))

    return Embeddings().eval()


def export_network(
    network: torch.nn.Module,
    size: int,
    normalisation: tuple[tuple[float, ...], tuple[float, ...]],
    out: Path,
    description: str,
    opset: int = 18,
) -> float:
    """Export, then return the largest difference between ONNX Runtime's
    embeddings and PyTorch's for two random pictures."""
    import onnx
    import onnxruntime as ort
    import torch

    model = _embeddings(network)
    pictures = torch.randn(2, 3, size, size, generator=torch.Generator().manual_seed(0))
    out.parent.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        torch.onnx.export(
            model,
            (pictures,),
            str(out),
            input_names=["images"],
            output_names=["embeddings"],
            dynamic_axes={"images": {0: "batch"}, "embeddings": {0: "batch"}},
            opset_version=opset,
            dynamo=False,
        )
        expected = model(pictures).numpy()
    graph = onnx.load(str(out))
    mean, std = normalisation
    onnx.helper.set_model_props(
        graph,
        {
            "mean": ",".join(f"{value:g}" for value in mean),
            "std": ",".join(f"{value:g}" for value in std),
            "description": description,
        },
    )
    onnx.checker.check_model(graph)
    onnx.save(graph, str(out))
    session = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    produced = session.run(None, {"images": pictures.numpy()})[0]
    return float(np.abs(produced - expected).max())


def export_preset(
    spec: str, checkpoint: Path | None, out: Path, opset: int = 18
) -> float:
    """A preset's network, with its published weights or a fine-tuned checkpoint."""
    chosen = preset(spec)
    description = spec + (f" fine-tuned as {checkpoint.name}" if checkpoint else "")
    return export_network(
        load_network(chosen, checkpoint),
        chosen.size,
        chosen.normalisation,
        out,
        description,
        opset,
    )
