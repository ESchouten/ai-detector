"""Embedding networks behind one interface; PyTorch loads only when one is built."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

if TYPE_CHECKING:
    import torch

IMAGENET = ((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
HALF = ((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))


class Embedder(Protocol):
    """Describe pictures as L2-normalised float32 rows, one per path, in order."""

    name: str

    def embed(self, paths: Sequence[Path]) -> NDArray[np.float32]: ...


@dataclass(frozen=True)
class Preset:
    loader: str
    model: str
    size: int
    normalisation: tuple[tuple[float, ...], tuple[float, ...]]
    options: dict[str, Any] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    # BVRA's wildlife re-ID Swin transformers, CC BY-NC 4.0.
    "megadescriptor-l-384": Preset(
        "timm", "hf-hub:BVRA/MegaDescriptor-L-384", 384, HALF
    ),
    "megadescriptor-b-224": Preset(
        "timm", "hf-hub:BVRA/MegaDescriptor-B-224", 224, HALF
    ),
    "megadescriptor-t-224": Preset(
        "timm", "hf-hub:BVRA/MegaDescriptor-T-224", 224, HALF
    ),
    # Wild Me's multispecies EfficientNetV2; its model card states no licence.
    "miewid-msv3": Preset(
        "transformers", "conservationxlabs/miewid-msv3", 440, IMAGENET
    ),
    "dinov2-s": Preset(
        "timm",
        "vit_small_patch14_dinov2.lvd142m",
        224,
        IMAGENET,
        {"img_size": 224},
    ),
    "dinov2-b": Preset(
        "timm", "vit_base_patch14_dinov2.lvd142m", 224, IMAGENET, {"img_size": 224}
    ),
    "dinov2-l": Preset(
        "timm", "vit_large_patch14_dinov2.lvd142m", 224, IMAGENET, {"img_size": 224}
    ),
    # Meta's DINOv3 licence; weights may need the licence accepted on Hugging Face.
    "dinov3-s": Preset(
        "timm", "vit_small_patch16_dinov3.lvd1689m", 224, IMAGENET, {"img_size": 224}
    ),
    "dinov3-b": Preset(
        "timm", "vit_base_patch16_dinov3.lvd1689m", 224, IMAGENET, {"img_size": 224}
    ),
    "dinov3-l": Preset(
        "timm", "vit_large_patch16_dinov3.lvd1689m", 224, IMAGENET, {"img_size": 224}
    ),
}


def preset(spec: str) -> Preset:
    """A named preset, or `timm:<model>` / `timm:<model>@<size>` for any timm model."""
    if spec in PRESETS:
        return PRESETS[spec]
    if spec.startswith("timm:"):
        model, _, size = spec.removeprefix("timm:").partition("@")
        return Preset("timm", model, int(size) if size else 224, IMAGENET)
    raise ValueError(
        f"Unknown model {spec!r}; use one of {', '.join(PRESETS)} or timm:<name>[@size]"
    )


def default_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class TorchEmbedder:
    """Square-resize, normalise, and run a feature network in batches."""

    def __init__(
        self,
        name: str,
        network: torch.nn.Module,
        size: int,
        normalisation: tuple[tuple[float, ...], tuple[float, ...]],
        *,
        grayscale: bool = False,
        batch_size: int = 32,
        device: str | None = None,
    ):
        import torch

        self.name = name
        self.size = size
        self.grayscale = grayscale
        self.batch_size = batch_size
        self.device = torch.device(device or default_device())
        self.network = network.eval().to(self.device)
        mean, std = normalisation
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)

    def _pixels(self, path: Path) -> NDArray[np.float32]:
        with Image.open(path) as picture:
            # Without colour a red cow is not taken for the herd's other red cow,
            # and daylight looks like infrared.
            picture = picture.convert("L" if self.grayscale else "RGB")
            picture = picture.convert("RGB").resize(
                (self.size, self.size), Image.Resampling.BICUBIC
            )
            pixels = np.asarray(picture, dtype=np.float32) / 255
        normalised = (pixels - self.mean) / self.std
        return normalised.transpose(2, 0, 1).astype(np.float32, copy=False)

    def embed(self, paths: Sequence[Path]) -> NDArray[np.float32]:
        import torch

        rows = []
        with torch.inference_mode():
            for start in range(0, len(paths), self.batch_size):
                batch = np.stack(
                    [
                        self._pixels(path)
                        for path in paths[start : start + self.batch_size]
                    ]
                )
                output = self.network(torch.from_numpy(batch).to(self.device))
                features = _features(output).float()
                rows.append(
                    torch.nn.functional.normalize(features, dim=1).cpu().numpy()
                )
        if not rows:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(rows).astype(np.float32, copy=False)


def _features(output: Any) -> torch.Tensor:
    import torch

    if isinstance(output, torch.Tensor):
        return output.flatten(1)
    for attribute in ("pooler_output", "embeddings", "last_hidden_state"):
        value = getattr(output, attribute, None)
        if isinstance(value, torch.Tensor):
            return value.flatten(1) if value.ndim <= 2 else value[:, 0]
    if isinstance(output, (tuple, list)) and output:
        return _features(output[0])
    raise TypeError(f"Cannot find embeddings in a {type(output).__name__}")


def _timm_network(
    model: str, checkpoint: Path | None, options: dict[str, Any]
) -> torch.nn.Module:
    import timm

    network = timm.create_model(
        model, pretrained=checkpoint is None, num_classes=0, **options
    )
    if checkpoint is not None:
        _load_checkpoint(network, checkpoint)
    return network


def _transformers_network(
    model: str, checkpoint: Path | None, options: dict[str, Any]
) -> torch.nn.Module:
    from transformers import AutoModel

    if checkpoint is not None:
        raise ValueError("A checkpoint replaces timm weights only")
    # The model card's own loading code; it runs code published with the weights.
    return AutoModel.from_pretrained(model, trust_remote_code=True, **options)


def _load_checkpoint(network: torch.nn.Module, path: Path) -> None:
    import torch

    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        state = load_file(path)
    else:
        state = torch.load(path, map_location="cpu", weights_only=True)
        for key in ("state_dict", "model", "network"):
            if isinstance(state, dict) and isinstance(state.get(key), dict):
                state = state[key]
    state = {name.removeprefix("module."): tensor for name, tensor in state.items()}
    result = network.load_state_dict(state, strict=False)
    loaded = len(state) - len(result.unexpected_keys)
    if loaded == 0:
        raise ValueError(f"{path} has no weights for this network")


_LOADERS: dict[str, Callable[[str, Path | None, dict[str, Any]], torch.nn.Module]] = {
    "timm": _timm_network,
    "transformers": _transformers_network,
}


def build(
    spec: str,
    *,
    checkpoint: Path | None = None,
    grayscale: bool = False,
    batch_size: int = 32,
    device: str | None = None,
) -> TorchEmbedder:
    chosen = preset(spec)
    network = _LOADERS[chosen.loader](chosen.model, checkpoint, chosen.options)
    name = (
        spec
        + ("+gray" if grayscale else "")
        + (f"+{checkpoint.name}" if checkpoint else "")
    )
    return TorchEmbedder(
        name,
        network,
        chosen.size,
        chosen.normalisation,
        grayscale=grayscale,
        batch_size=batch_size,
        device=device,
    )
