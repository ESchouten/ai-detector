"""Fine-tune an embedding network on labelled cows with a sub-centre ArcFace head.

The head is thrown away after training; only the backbone is saved, so the
benchmark loads the result as an ordinary checkpoint.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from reid.backbones import default_device, features, load_network, preset
from reid.manifest import Crop

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class TrainOptions:
    epochs: int = 10
    identities_per_batch: int = 16
    crops_per_identity: int = 4
    learning_rate: float = 3e-5
    head_learning_rate: float = 1e-3
    weight_decay: float = 0.05
    margin: float = 0.3
    scale: float = 30.0
    subcentres: int = 3
    grayscale: bool = False
    seed: int = 0


def batches(
    crops: Sequence[Crop], options: TrainOptions, rng: np.random.Generator
) -> Iterator[list[int]]:
    """One epoch of P×K batches: P animals with K crops each, every animal once.

    Animals with a single crop give no positive pair and are left out.
    """
    by_identity: dict[str, list[int]] = {}
    for index, crop in enumerate(crops):
        by_identity.setdefault(crop.identity, []).append(index)
    eligible = [indices for indices in by_identity.values() if len(indices) > 1]
    order = rng.permutation(len(eligible))
    step = options.identities_per_batch
    for start in range(0, len(order) - step + 1, step):
        batch: list[int] = []
        for position in order[start : start + step]:
            indices = eligible[position]
            batch.extend(
                rng.choice(
                    indices,
                    size=options.crops_per_identity,
                    replace=len(indices) < options.crops_per_identity,
                ).tolist()
            )
        yield batch


def _augmented(
    path: Path,
    size: int,
    normalisation: tuple[tuple[float, ...], tuple[float, ...]],
    grayscale: bool,
    rng: np.random.Generator,
) -> np.ndarray:
    """Random crop, scale and brightness; no mirroring, which would invent a coat."""
    with Image.open(path) as picture:
        picture = picture.convert("L" if grayscale else "RGB").convert("RGB")
        width, height = picture.size
        keep = rng.uniform(0.75, 1.0)
        w, h = max(1, round(width * keep)), max(1, round(height * keep))
        left = int(rng.integers(0, width - w + 1))
        top = int(rng.integers(0, height - h + 1))
        picture = picture.crop((left, top, left + w, top + h)).resize(
            (size, size), Image.Resampling.BICUBIC
        )
        pixels = np.asarray(picture, dtype=np.float32) / 255
    pixels = np.clip(pixels * rng.uniform(0.7, 1.3) + rng.uniform(-0.1, 0.1), 0, 1)
    mean, std = (np.asarray(value, dtype=np.float32) for value in normalisation)
    return ((pixels - mean) / std).transpose(2, 0, 1).astype(np.float32)


def _arcface_loss(
    centres: torch.Tensor,
    embeddings: torch.Tensor,
    labels: torch.Tensor,
    options: TrainOptions,
) -> torch.Tensor:
    """Sub-centre ArcFace: each animal keeps several centres, so a dirty or night
    picture of her can sit near one of them without dragging the others."""
    import torch
    import torch.nn.functional as functional

    classes = centres.shape[0] // options.subcentres
    cosine = functional.normalize(embeddings) @ functional.normalize(centres).T
    cosine = cosine.view(-1, classes, options.subcentres).amax(dim=2)
    angle = torch.acos(cosine.clamp(-1 + 1e-6, 1 - 1e-6))
    target = functional.one_hot(labels, classes).bool()
    logits = torch.where(target, torch.cos(angle + options.margin), cosine)
    return functional.cross_entropy(options.scale * logits, labels)


def train(
    crops: Sequence[Crop],
    spec: str,
    out: Path,
    options: TrainOptions,
    *,
    checkpoint: Path | None = None,
    device: str | None = None,
) -> Path:
    """Fine-tune `spec` on the crops' identities; returns the saved backbone."""
    import torch
    from safetensors.torch import save_file

    chosen = preset(spec)
    if chosen.loader != "timm":
        raise ValueError("Fine-tuning supports timm models")
    rng = np.random.default_rng(options.seed)
    torch.manual_seed(options.seed)
    names = sorted({crop.identity for crop in crops})
    labels = {name: index for index, name in enumerate(names)}
    target = torch.device(device or default_device())
    network = load_network(chosen, checkpoint).to(target)
    with torch.no_grad():
        probe = torch.zeros(1, 3, chosen.size, chosen.size, device=target)
        dimensions = features(network.eval()(probe)).shape[1]
    centres = torch.nn.Parameter(
        torch.randn(len(names) * options.subcentres, dimensions, device=target) * 0.01
    )
    optimiser = torch.optim.AdamW(
        [
            {"params": network.parameters(), "lr": options.learning_rate},
            {"params": [centres], "lr": options.head_learning_rate},
        ],
        weight_decay=options.weight_decay,
    )
    steps = options.epochs * max(
        1,
        sum(1 for _ in batches(crops, options, np.random.default_rng(0))),
    )
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimiser, lambda step: 0.5 * (1 + math.cos(math.pi * min(step / steps, 1)))
    )
    history = []
    for epoch in range(options.epochs):
        network.train()
        losses = []
        for batch in batches(crops, options, rng):
            pixels = torch.from_numpy(
                np.stack(
                    [
                        _augmented(
                            crops[i].path,
                            chosen.size,
                            chosen.normalisation,
                            options.grayscale,
                            rng,
                        )
                        for i in batch
                    ]
                )
            ).to(target)
            truth = torch.tensor(
                [labels[crops[i].identity] for i in batch], device=target
            )
            loss = _arcface_loss(centres, features(network(pixels)), truth, options)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            schedule.step()
            losses.append(loss.item())
        average = float(np.mean(losses)) if losses else math.nan
        history.append(average)
        print(
            f"epoch {epoch + 1}/{options.epochs}: loss {average:.3f}", file=sys.stderr
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    save_file(
        {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in network.state_dict().items()
        },
        out,
    )
    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "model": spec,
                "start": str(checkpoint) if checkpoint else None,
                "crops": len(crops),
                "identities": len(names),
                "options": asdict(options),
                "loss": history,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out
