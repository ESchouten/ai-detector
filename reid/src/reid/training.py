"""Fine-tune an embedding network on labelled cows with a sub-centre ArcFace head.

The head is thrown away after training; only the backbone is saved, so the
benchmark loads the result as an ordinary checkpoint.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
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
    # Pictures through the network at once. A smaller chunk saves memory; every
    # picture's loss stands alone, so only batch-norm statistics change.
    chunk: int | None = None


def batches(
    crops: Sequence[Crop],
    options: TrainOptions,
    rng: np.random.Generator,
    farms: Sequence[str] | None = None,
) -> Iterator[list[int]]:
    """One epoch of P×K batches: P animals with K crops each, every animal once.

    With `farms`, a batch holds cows of one farm only: cows from another barn are
    told apart by the barn, which teaches the network nothing about cows. A farm
    with fewer than P animals gives one smaller batch. Animals with a single
    crop give no positive pair and are left out.
    """
    by_identity: dict[str, list[int]] = {}
    for index, crop in enumerate(crops):
        by_identity.setdefault(crop.identity, []).append(index)
    by_farm: dict[str, list[list[int]]] = {}
    for indices in by_identity.values():
        if len(indices) > 1:
            farm = farms[indices[0]] if farms is not None else ""
            by_farm.setdefault(farm, []).append(indices)
    step = options.identities_per_batch
    groups: list[list[list[int]]] = []
    for animals in by_farm.values():
        order = rng.permutation(len(animals))
        for start in range(0, len(order), step):
            chunk = order[start : start + step]
            if len(chunk) == step or (start == 0 and len(chunk) > 1):
                groups.append([animals[position] for position in chunk])
    for group in rng.permutation(len(groups)):
        batch: list[int] = []
        for indices in groups[group]:
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
    farms: Sequence[str] | None = None,
) -> Path:
    """Fine-tune `spec` on the crops' identities; returns the saved backbone.

    `farms` names each crop's farm, so batches never mix farms.
    """
    import torch

    chosen = preset(spec)
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
        sum(1 for _ in batches(crops, options, np.random.default_rng(0), farms)),
    )
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimiser, lambda step: 0.5 * (1 + math.cos(math.pi * min(step / steps, 1)))
    )
    record = {
        "model": spec,
        "start": str(checkpoint) if checkpoint else None,
        "crops": len(crops),
        "identities": len(names),
        "farms": sorted(set(farms)) if farms is not None else None,
        "options": asdict(options),
    }
    history: list[float] = []
    size = options.chunk or options.identities_per_batch * options.crops_per_identity
    with ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        for epoch in range(options.epochs):
            network.train()
            losses = []
            for batch in batches(crops, options, rng, farms):
                # One seed per picture keeps augmentation reproducible across threads.
                seeds = rng.integers(2**32, size=len(batch)).tolist()
                optimiser.zero_grad()
                total = 0.0
                for start in range(0, len(batch), size):
                    part = batch[start : start + size]
                    pixels = np.stack(
                        list(
                            pool.map(
                                lambda index, seed: _augmented(
                                    crops[index].path,
                                    chosen.size,
                                    chosen.normalisation,
                                    options.grayscale,
                                    np.random.default_rng(seed),
                                ),
                                part,
                                seeds[start : start + size],
                            )
                        )
                    )
                    truth = torch.tensor(
                        [labels[crops[i].identity] for i in part], device=target
                    )
                    embedded = features(network(torch.from_numpy(pixels).to(target)))
                    # Chunk losses add up to the batch's mean loss.
                    loss = _arcface_loss(centres, embedded, truth, options)
                    loss = loss * len(part) / len(batch)
                    loss.backward()
                    total += loss.item()
                optimiser.step()
                schedule.step()
                losses.append(total)
            average = float(np.mean(losses)) if losses else math.nan
            history.append(average)
            print(
                f"epoch {epoch + 1}/{options.epochs}: loss {average:.3f}",
                file=sys.stderr,
            )
            # Saved every epoch, so a crash late in a long run keeps the last one.
            _save(network, out, {**record, "loss": history})
    return out


def _save(network: torch.nn.Module, out: Path, record: dict) -> None:
    """Write the backbone and its record, replacing the previous epoch's whole."""
    from safetensors.torch import save_file

    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    save_file(
        {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in network.state_dict().items()
        },
        partial,
    )
    os.replace(partial, out)
    out.with_suffix(".json").write_text(
        json.dumps({**record, "epochs": len(record["loss"])}, indent=2) + "\n",
        encoding="utf-8",
    )
