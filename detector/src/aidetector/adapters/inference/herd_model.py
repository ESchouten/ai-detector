"""A herd's own identity model, taught from the photographs its farmer confirmed.

Networks that already tell animals apart are adapted to the confirmed herd:
each learns a normalised descriptor by learning to sort the photographs by
cow. A new crop is then compared with the descriptors of those photographs.
Two kinds of network take part, because a stranger that one kind mistakes for
a confirmed cow rarely fools the other. Deciding whether a similarity is good
enough to show a name belongs to the domain rules, not here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event, Lock
from typing import Any

import cv2
import numpy as np
import torch
from numpy.typing import NDArray

from aidetector.adapters.inference.device import mps_inference
from aidetector.adapters.inference.miewid import MiewidNetwork

logger = logging.getLogger(__name__)

MEAN = (0.485, 0.456, 0.406)
DEVIATION = (0.229, 0.224, 0.225)
PADDING = (104, 116, 124)
# Blue, green and red weigh this much in how light a pixel looks.
LUMINANCE = (0.114, 0.587, 0.299)
# Cosine-margin loss: similarities are scaled, the true cow's is first reduced.
SCALE = 24.0
MARGIN = 0.25
# A small herd is still shown this many photographs, drawn again and again.
MINIMUM_DRAWS = 5120
PREPARERS = 8


class HerdNetwork(torch.nn.Module):
    """A pretrained network and, to learn against, one direction per cow."""

    size: int
    batch: int
    dimension: int
    directions: torch.nn.Parameter

    def start(self, weights: Path) -> None:
        """Take the pretrained weights; the directions always begin afresh."""
        raise NotImplementedError

    def describe(self, pixels: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError

    def fit(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """A crop as the square picture this network was pretrained on."""
        raise NotImplementedError

    def rates(self) -> list[dict[str, Any]]:
        """What learns slowly because it is pretrained, and what starts afresh."""
        raise NotImplementedError

    def similarities(self, pixels: torch.Tensor) -> torch.Tensor:
        return (
            self.describe(pixels)
            @ torch.nn.functional.normalize(self.directions, dim=1).T
        )


class CattleNetwork(HerdNetwork):
    """DINOv2-small and a projection, started from weights taught other farms' cows."""

    size = 224
    batch = 32
    dimension = 256

    def __init__(self, identities: int):
        super().__init__()
        from transformers.models.dinov2.configuration_dinov2 import Dinov2Config
        from transformers.models.dinov2.modeling_dinov2 import Dinov2Model

        # The published facebook/dinov2-small architecture, built without a download.
        self.backbone = Dinov2Model(
            Dinov2Config(hidden_size=384, num_attention_heads=6, image_size=518)
        )
        self.project = torch.nn.Sequential(
            torch.nn.LayerNorm(768), torch.nn.Linear(768, self.dimension)
        )
        self.directions = torch.nn.Parameter(
            torch.randn(identities, self.dimension) * 0.01
        )

    def start(self, weights: Path) -> None:
        from safetensors.torch import load_file

        self.load_state_dict(load_file(str(weights)), strict=False)

    def describe(self, pixels: torch.Tensor) -> torch.Tensor:
        tokens = self.backbone(pixel_values=pixels).last_hidden_state
        pooled = torch.cat([tokens[:, 0], tokens[:, 1:].mean(1)], dim=1)
        return torch.nn.functional.normalize(self.project(pooled), dim=1)

    def fit(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Keep the whole animal and its proportions; pad the shorter side."""
        height, width = image.shape[:2]
        scale = self.size / max(height, width)
        resized = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )
        canvas = np.full((self.size, self.size, 3), PADDING, dtype=np.uint8)
        top = (self.size - resized.shape[0]) // 2
        left = (self.size - resized.shape[1]) // 2
        canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
        return canvas

    def rates(self) -> list[dict[str, Any]]:
        return [
            {"params": self.backbone.parameters(), "lr": 3e-5},
            {"params": [*self.project.parameters(), self.directions], "lr": 1e-3},
        ]


class AnimalNetwork(HerdNetwork):
    """MIEWid as published, which was taught to re-identify animals of many species."""

    # Smaller than the published 440 pixels: a tracked cow is seldom larger,
    # and learning at 440 needs more memory than a farm computer has.
    size = 288
    batch = 8
    dimension = 2152

    def __init__(self, identities: int):
        super().__init__()
        self.published = MiewidNetwork()
        self.directions = torch.nn.Parameter(
            torch.randn(identities, self.dimension) * 0.01
        )

    def start(self, weights: Path) -> None:
        from safetensors.torch import load_file

        self.published.load_state_dict(load_file(str(weights)))

    def train(self, mode: bool = True) -> AnimalNetwork:
        """The published running statistics stay: batches here are too small to renew them."""
        super().train(mode)
        for module in self.modules():
            if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
                module.eval()
        return self

    def describe(self, pixels: torch.Tensor) -> torch.Tensor:
        return torch.nn.functional.normalize(self.published(pixels), dim=1)

    def fit(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        return cv2.resize(image, (self.size, self.size), interpolation=cv2.INTER_LINEAR)

    def rates(self) -> list[dict[str, Any]]:
        return [
            {"params": self.published.parameters(), "lr": 3e-5},
            {"params": [self.directions], "lr": 1e-3},
        ]


def vary(
    image: NDArray[np.uint8],
    generator: np.random.Generator,
    fit: Callable[[NDArray[np.uint8]], NDArray[np.uint8]],
) -> NDArray[np.uint8]:
    """Views a fixed camera plausibly produces: shifted, turned, darker, blurred."""
    height, width = image.shape[:2]
    scale = generator.uniform(0.7, 1.0)
    crop_height, crop_width = max(8, int(height * scale)), max(8, int(width * scale))
    top = generator.integers(0, height - crop_height + 1)
    left = generator.integers(0, width - crop_width + 1)
    image = fit(image[top : top + crop_height, left : left + crop_width])
    size = image.shape[0]
    turn = cv2.getRotationMatrix2D((size / 2, size / 2), generator.uniform(-20, 20), 1)
    image = cv2.warpAffine(
        image, turn, (size, size), borderMode=cv2.BORDER_CONSTANT, borderValue=PADDING
    )
    pixels = image.astype(np.float32)
    pixels = pixels * generator.uniform(0.6, 1.4) + generator.uniform(-25, 25)
    if generator.random() < 0.3:
        kernel = int(generator.choice([3, 5, 7]))
        pixels = cv2.GaussianBlur(pixels, (kernel, kernel), 0)
    if generator.random() < 0.5:
        # A rail or another animal hides part of the coat.
        hidden_height = int(size * generator.uniform(0.1, 0.35))
        hidden_width = int(size * generator.uniform(0.1, 0.35))
        y = generator.integers(0, size - hidden_height)
        x = generator.integers(0, size - hidden_width)
        pixels[y : y + hidden_height, x : x + hidden_width] = generator.uniform(0, 255)
    return np.clip(pixels, 0, 255).astype(np.uint8)


def to_tensor(images: Sequence[NDArray[np.uint8]]) -> torch.Tensor:
    """Network input without colour.

    A coat then looks the same by day and under infrared light at night, and
    its colour cannot stand in for its pattern: a stranger of the same colour
    as a confirmed cow is otherwise taken for that cow.
    """
    light = np.stack(images).astype(np.float32) @ np.array(LUMINANCE, np.float32)
    pixels = (light[..., None] / 255.0 - MEAN) / DEVIATION
    # An Apple GPU cannot learn through convolutions from a transposed view.
    return torch.from_numpy(
        np.ascontiguousarray(pixels.transpose(0, 3, 1, 2), dtype=np.float32)
    )


def choose_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def learn(
    read: Callable[[str], NDArray[np.uint8]],
    samples: Sequence[tuple[str, int]],
    network: HerdNetwork,
    device: str,
    stopped: Event | None = None,
    *,
    passes: int = 3,
    minimum_draws: int = MINIMUM_DRAWS,
    seed: int = 0,
) -> HerdNetwork:
    """Adapt a started network to `samples`, pairs of photograph and cow index.

    Every cow is drawn equally often, however many photographs it has.
    """
    torch.manual_seed(seed)
    identities = network.directions.shape[0]
    scope = mps_inference if device == "mps" else nullcontext
    with scope():
        network.to(device)
    owners = np.array([owner for _, owner in samples])
    weights = 1.0 / np.bincount(owners, minlength=identities)[owners]
    # A small herd still gets full batches, and enough of them to learn from:
    # photographs are drawn with replacement.
    steps = max(1, len(samples) // network.batch)
    passes = max(passes, math.ceil(minimum_draws / (steps * network.batch)))
    optimizer = torch.optim.AdamW(network.rates(), weight_decay=0.05)
    total = passes * steps
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: (
            min(1.0, (step + 1) / steps)
            * 0.5
            * (1 + math.cos(math.pi * min(step, total) / total))
        ),
    )
    draws = torch.Generator().manual_seed(seed)
    plan: list[tuple[int, list[int]]] = []
    for turn in range(passes):
        order = torch.multinomial(
            torch.from_numpy(weights),
            steps * network.batch,
            replacement=True,
            generator=draws,
        ).tolist()
        plan.extend(
            (turn, order[first : first + network.batch])
            for first in range(0, len(order), network.batch)
        )

    def view(turn: int, index: int) -> NDArray[np.uint8]:
        return vary(
            read(samples[index][0]),
            np.random.default_rng((seed, turn, index)),
            network.fit,
        )

    network.train()
    right = 0
    # Reading and varying photographs takes longer than learning from them,
    # so other threads prepare the next step's while the network learns.
    with ThreadPoolExecutor(PREPARERS, "herd-photographs") as pool:

        def prepare(step: int) -> list[Future[NDArray[np.uint8]]]:
            turn, chosen = plan[step]
            return [pool.submit(view, turn, index) for index in chosen]

        coming = prepare(0)
        for step, (turn, chosen) in enumerate(plan):
            if stopped is not None and stopped.is_set():
                raise CancelledError("Herd learning stopped")
            ready, coming = coming, prepare(step + 1) if step + 1 < total else []
            pixels = to_tensor([photograph.result() for photograph in ready])
            target = torch.from_numpy(owners[chosen])
            # Other models on an Apple GPU run between steps, never during one.
            with scope():
                pixels, target = pixels.to(device), target.to(device)
                similarity = network.similarities(pixels)
                loss = torch.nn.functional.cross_entropy(
                    SCALE
                    * (
                        similarity
                        - MARGIN * torch.nn.functional.one_hot(target, identities)
                    ),
                    target,
                )
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                schedule.step()
                right += int((similarity.argmax(1) == target).sum())
            if (step + 1) % steps == 0:
                logger.info(
                    "Learning the herd: %s round %d of %d, %.1f%% of the photographs recognised",
                    type(network).__name__,
                    turn + 1,
                    passes,
                    100 * right / (steps * network.batch),
                )
                right = 0
    return network.eval().requires_grad_(False)


class HerdEncoder:
    """Describes crops with several networks taught from the same photographs.

    A network alone is swayed by the order its photographs happened to come
    in, and each kind by what it was pretrained on. A descriptor has one part
    per kind of network: the vectors of that kind's networks side by side,
    scaled so that a dot product of two parts is the mean similarity over
    those networks. The kinds are compared separately.
    """

    def __init__(self, networks: Sequence[HerdNetwork], device: str, fingerprint: str):
        self.networks = tuple(networks)
        self.device = device
        self.fingerprint = fingerprint
        self.dimension = sum(network.dimension for network in self.networks)
        kinds = [type(network) for network in self.networks]
        self._weights = tuple(kinds.count(kind) ** -0.5 for kind in kinds)
        # Networks of one kind stand together, so a part is their joint width.
        self.parts = tuple(
            sum(network.dimension for network in self.networks if type(network) is kind)
            for kind in dict.fromkeys(kinds)
        )
        self._lock = Lock()

    def encode(self, images: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]:
        if not images:
            return np.empty((0, self.dimension), dtype=np.float32)
        pictures = {
            kind: to_tensor([network.fit(image) for image in images])
            for kind, network in {
                type(network): network for network in self.networks
            }.items()
        }
        scope = mps_inference if self.device == "mps" else nullcontext
        with self._lock, scope(), torch.inference_mode():
            described = torch.cat(
                [
                    network.describe(pictures[type(network)].to(self.device)) * weight
                    for network, weight in zip(
                        self.networks, self._weights, strict=True
                    )
                ],
                dim=1,
            )
            return described.cpu().numpy().copy()
