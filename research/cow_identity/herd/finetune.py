"""Adapt a pretrained backbone to one herd's confirmed photographs.

The network learns a normalised descriptor and one direction per cow with a
cosine-margin loss. Naming later compares a crop's descriptor with those
directions, so an animal that resembles none of them can be refused.
"""

import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from features import IMAGENET_MEAN, IMAGENET_STD, letterbox

BACKBONES = {
    "dinov2-s": ("facebook/dinov2-small", 384),
    "dinov2-b": ("facebook/dinov2-base", 768),
}


class HerdNetwork(torch.nn.Module):
    def __init__(self, backbone, classes, dimension=256, anchors=0):
        super().__init__()
        from transformers import AutoModel

        source, width = BACKBONES[backbone]
        self.backbone = AutoModel.from_pretrained(source)
        self.project = torch.nn.Sequential(
            torch.nn.LayerNorm(2 * width), torch.nn.Linear(2 * width, dimension)
        )
        self.directions = torch.nn.Parameter(torch.randn(classes, dimension) * 0.01)
        # Directions of other farms' cows, kept as they were learned: the herd's
        # descriptors must stay clear of them without seeing those cows again.
        self.register_buffer("anchors", torch.zeros(anchors, dimension))

    def describe(self, pixels):
        tokens = self.backbone(pixel_values=pixels).last_hidden_state
        pooled = torch.cat([tokens[:, 0], tokens[:, 1:].mean(1)], dim=1)
        return torch.nn.functional.normalize(self.project(pooled), dim=1)

    def similarities(self, descriptors):
        every = torch.cat([self.directions, self.anchors])
        return descriptors @ torch.nn.functional.normalize(every, dim=1).T


def augment(image, generator, size, turn=20.0):
    """Views a fixed camera plausibly produces: shifted, rotated, darker, colourless."""
    height, width = image.shape[:2]
    scale = generator.uniform(0.7, 1.0)
    crop_h, crop_w = max(8, int(height * scale)), max(8, int(width * scale))
    top = generator.integers(0, height - crop_h + 1)
    left = generator.integers(0, width - crop_w + 1)
    image = image[top : top + crop_h, left : left + crop_w]
    image = letterbox(image, size)
    angle = generator.uniform(-turn, turn)
    matrix = cv2.getRotationMatrix2D((size / 2, size / 2), angle, 1.0)
    image = cv2.warpAffine(
        image, matrix, (size, size), borderMode=cv2.BORDER_CONSTANT, borderValue=(104, 116, 124)
    )
    pixels = image.astype(np.float32)
    pixels = pixels * generator.uniform(0.6, 1.4) + generator.uniform(-25, 25)
    if generator.random() < 0.35:
        pixels[:] = pixels.mean(2, keepdims=True)
    if generator.random() < 0.3:
        kernel = int(generator.choice([3, 5, 7]))
        pixels = cv2.GaussianBlur(pixels, (kernel, kernel), 0)
    if generator.random() < 0.5:
        # A rail or another animal hides part of the coat.
        erase_h = int(size * generator.uniform(0.1, 0.35))
        erase_w = int(size * generator.uniform(0.1, 0.35))
        y = generator.integers(0, size - erase_h)
        x = generator.integers(0, size - erase_w)
        pixels[y : y + erase_h, x : x + erase_w] = generator.uniform(0, 255)
    return np.clip(pixels, 0, 255).astype(np.uint8)


def normalise(image):
    pixels = image[:, :, ::-1].astype(np.float32) / 255.0
    return ((pixels - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1).astype(np.float32)


class _Training(torch.utils.data.Dataset):
    def __init__(self, paths, targets, size, seed, turn, mirrored):
        self.paths, self.targets, self.size, self.seed = paths, targets, size, seed
        self.turn, self.mirrored = turn, mirrored
        self.epoch = 0

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        generator = np.random.default_rng((self.seed, self.epoch, index))
        image = cv2.imread(self.paths[index])
        target = self.targets[index]
        if self.mirrored and target < self.mirrored and generator.random() < 0.5:
            # A mirrored coat belongs to no real animal: it is this cow's impostor.
            image = image[:, ::-1]
            target += self.mirrored
        return normalise(augment(image, generator, self.size, self.turn)), target


class _Plain(torch.utils.data.Dataset):
    def __init__(self, paths, size):
        self.paths, self.size = paths, size

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        return normalise(letterbox(cv2.imread(self.paths[index]), self.size))


def train(
    paths,
    labels,
    backbone="dinov2-s",
    size=224,
    epochs=12,
    batch=32,
    rate=3e-5,
    head_rate=1e-3,
    scale=24.0,
    margin=0.25,
    turn=20.0,
    mirror=False,
    others=None,
    start=None,
    anchor=False,
    min_steps=0,
    seed=0,
    device="mps",
    workers=6,
    log=print,
):
    """Return (network, classes). Every cow of the herd is drawn equally often.

    With `mirror`, each cow also gets an impostor class made of its mirrored
    photographs. `others` is (paths, labels) of cows from other farms; half of
    every batch then shows them, each as a class of its own. Impostors and
    other cows follow the herd in the direction table and are never named.
    """
    torch.manual_seed(seed)
    classes = sorted(set(labels))
    index = {label: position for position, label in enumerate(classes)}
    targets = [index[label] for label in labels]
    outputs = len(classes) * (2 if mirror else 1)
    paths = list(paths)
    weights = np.full(len(targets), 1.0)
    counts = np.bincount(targets, minlength=len(classes))
    weights /= counts[targets] * len(classes)
    drawn = len(targets)
    if others is not None:
        other_paths, other_labels = others
        foreign = sorted(set(other_labels))
        position = {label: outputs + place for place, label in enumerate(foreign)}
        foreign_targets = [position[label] for label in other_labels]
        foreign_counts = np.bincount(foreign_targets, minlength=outputs + len(foreign))
        weights = np.concatenate(
            [weights, 1.0 / (foreign_counts[foreign_targets] * len(foreign))]
        )
        paths += list(other_paths)
        targets += foreign_targets
        outputs += len(foreign)
        drawn *= 2
    state = None
    if start is not None:
        # Begin from a backbone already taught to tell cows apart; the directions
        # belong to whichever animals that earlier model was shown.
        state = torch.load(start, map_location="cpu", weights_only=True)["state"]
        state.pop("anchors", None)
        foreign_directions = state.pop("directions")
    network = HerdNetwork(
        backbone, outputs, anchors=len(foreign_directions) if anchor else 0
    )
    if state is not None:
        network.load_state_dict(state, strict=False)
        if anchor:
            network.anchors.copy_(foreign_directions)
    network.to(device)
    outputs += len(network.anchors)
    sampler = torch.utils.data.WeightedRandomSampler(
        weights.tolist(),
        num_samples=drawn,
        generator=torch.Generator().manual_seed(seed),
    )
    dataset = _Training(paths, targets, size, seed, turn, len(classes) if mirror else 0)
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch,
        sampler=sampler,
        num_workers=workers,
        drop_last=True,
        persistent_workers=True,
    )
    groups = [
        {"params": [*network.project.parameters(), network.directions], "lr": head_rate}
    ]
    if rate > 0:
        groups.append({"params": network.backbone.parameters(), "lr": rate})
    else:
        # Only the projection and the directions learn; the backbone stays as given.
        network.backbone.requires_grad_(False)
    optimizer = torch.optim.AdamW(groups, weight_decay=0.05)
    # A handful of photographs would otherwise mean a handful of updates.
    epochs = max(epochs, math.ceil(min_steps / len(loader)))
    total = epochs * len(loader)
    warmup = len(loader)
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min(1.0, (step + 1) / warmup)
        * 0.5
        * (1 + math.cos(math.pi * min(step, total) / total)),
    )
    started = time.perf_counter()
    for epoch in range(epochs):
        dataset.epoch = epoch
        network.train()
        if rate == 0:
            network.backbone.eval()
        seen = correct = 0
        running = 0.0
        for step, (pixels, target) in enumerate(loader):
            if epoch == 0 and step in (1, 20):
                log(f"step {step}: {time.perf_counter() - started:.0f}s")
            pixels, target = pixels.to(device), target.to(device)
            similarity = network.similarities(network.describe(pixels))
            logits = scale * (
                similarity - margin * torch.nn.functional.one_hot(target, outputs)
            )
            loss = torch.nn.functional.cross_entropy(logits, target)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            schedule.step()
            running += loss.item() * len(target)
            correct += (similarity.argmax(1) == target).sum().item()
            seen += len(target)
        log(
            f"epoch {epoch + 1}/{epochs}: loss {running / seen:.3f}, "
            f"training accuracy {correct / seen:.3f}, {time.perf_counter() - started:.0f}s"
        )
    return network.eval(), classes


@torch.inference_mode()
def describe(network, paths, size=224, batch=64, device="mps", workers=6):
    loader = torch.utils.data.DataLoader(
        _Plain(paths, size), batch_size=batch, num_workers=workers
    )
    rows = [network.describe(pixels.to(device)).cpu().numpy() for pixels in loader]
    return np.concatenate(rows)


@torch.inference_mode()
def directions(network):
    every = torch.cat([network.directions, network.anchors])
    return torch.nn.functional.normalize(every, dim=1).cpu().numpy()


def run_key(paths, labels, settings):
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    for path, label in zip(paths, labels, strict=True):
        digest.update(f"{path}:{label}\n".encode())
    return digest.hexdigest()[:16]


def save(network, classes, settings, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state": network.state_dict(),
            "classes": classes,
            "settings": settings,
        },
        path,
    )


def load(path, device="mps"):
    saved = torch.load(path, map_location="cpu", weights_only=True)
    state = saved["state"]
    # Checkpoints written before rivals existed have none.
    state.setdefault("anchors", torch.zeros(0, state["directions"].shape[1]))
    network = HerdNetwork(
        saved["settings"]["backbone"], len(state["directions"]), anchors=len(state["anchors"])
    )
    network.load_state_dict(state)
    return network.eval().to(device), saved["classes"], saved["settings"]
