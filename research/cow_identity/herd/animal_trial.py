"""The trial that first adapted MIEWid to a herd, in a tidied copy.

The application now teaches this network itself (`AnimalNetwork` in the herd
model) and combines it with the cattle networks; use `app_scores` for new
runs. The trial produced the development comparisons of the second kind of
network before that: it adapts the published MIEWid to the confirmed
photographs with the cattle networks' recipe, describes photographs and
tracked crops, and writes score files beside the cattle networks' one: the
animal network alone, each kind scored by its own nearest photographs and
then averaged, and, given the cattle networks' similarities, the two kinds
mixed photograph by photograph.
"""

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
import torch
from safetensors.torch import load_file

from app_scores import tracked_crops
from ethz import confirmed_before

from aidetector.adapters.inference.miewid import MiewidNetwork

SIZE, BATCH, SCALE, MARGIN = 288, 8, 24.0, 0.25
MEAN, DEVIATION = np.float32((0.485, 0.456, 0.406)), np.float32((0.229, 0.224, 0.225))
LUMINANCE = np.float32((0.114, 0.587, 0.299))


def to_tensor(pictures):
    light = np.stack(pictures).astype(np.float32) @ LUMINANCE / 255.0
    pixels = ((light[..., None] - MEAN) / DEVIATION).transpose(0, 3, 1, 2)
    return torch.from_numpy(np.ascontiguousarray(pixels, dtype=np.float32))


def stretch(image):
    return cv2.resize(image, (SIZE, SIZE), interpolation=cv2.INTER_LINEAR)


def vary(image, generator):
    height, width = image.shape[:2]
    scale = generator.uniform(0.7, 1.0)
    crop_height, crop_width = max(8, int(height * scale)), max(8, int(width * scale))
    top = generator.integers(0, height - crop_height + 1)
    left = generator.integers(0, width - crop_width + 1)
    image = stretch(image[top : top + crop_height, left : left + crop_width])
    turn = cv2.getRotationMatrix2D((SIZE / 2, SIZE / 2), generator.uniform(-20, 20), 1)
    image = cv2.warpAffine(
        image, turn, (SIZE, SIZE), borderMode=cv2.BORDER_CONSTANT, borderValue=(104, 116, 124)
    )
    pixels = image.astype(np.float32) * generator.uniform(0.6, 1.4) + generator.uniform(-25, 25)
    if generator.random() < 0.3:
        kernel = int(generator.choice([3, 5, 9]))
        pixels = cv2.GaussianBlur(pixels, (kernel, kernel), 0)
    if generator.random() < 0.5:
        hidden_height = int(SIZE * generator.uniform(0.1, 0.35))
        hidden_width = int(SIZE * generator.uniform(0.1, 0.35))
        y = generator.integers(0, SIZE - hidden_height)
        x = generator.integers(0, SIZE - hidden_width)
        pixels[y : y + hidden_height, x : x + hidden_width] = generator.uniform(0, 255)
    return np.clip(pixels, 0, 255).astype(np.uint8)


def adapt(network, images, owners, cows, device, seed=0):
    torch.manual_seed(seed)
    directions = torch.nn.Parameter(torch.randn(cows, 2152, device=device) * 0.01)
    steps = 3 * len(images) // BATCH
    optimizer = torch.optim.AdamW(
        [{"params": network.parameters(), "lr": 3e-5}, {"params": [directions], "lr": 1e-3}],
        weight_decay=0.05,
    )
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min(1.0, (step + 1) / (steps // 3))
        * 0.5
        * (1 + math.cos(math.pi * min(step, steps) / steps)),
    )
    weights = 1.0 / np.bincount(owners, minlength=cows)[owners]
    order = torch.multinomial(
        torch.from_numpy(weights),
        steps * BATCH,
        replacement=True,
        generator=torch.Generator().manual_seed(seed),
    ).tolist()
    network.train()
    for module in network.modules():
        if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
            module.eval()
    for step in range(steps):
        chosen = order[step * BATCH : (step + 1) * BATCH]
        pixels = to_tensor(
            [vary(images[index], np.random.default_rng((seed, step, index))) for index in chosen]
        ).to(device)
        target = torch.from_numpy(owners[chosen]).to(device)
        similarity = (
            torch.nn.functional.normalize(network(pixels), dim=1)
            @ torch.nn.functional.normalize(directions, dim=1).T
        )
        loss = torch.nn.functional.cross_entropy(
            SCALE * (similarity - MARGIN * torch.nn.functional.one_hot(target, cows)), target
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        schedule.step()
    return network.eval().requires_grad_(False)


def describe(network, pictures, device):
    batches = []
    with torch.inference_mode():
        for first in range(0, len(pictures), 48):
            pixels = to_tensor([stretch(picture) for picture in pictures[first : first + 48]])
            batches.append(
                torch.nn.functional.normalize(network(pixels.to(device)), dim=1).cpu().numpy()
            )
    return np.concatenate(batches)


def nearest(similarity, owners, classes):
    return np.stack(
        [np.sort(similarity[:, owners == cow], axis=1)[:, -2:].mean(1) for cow in classes], 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Publisher crops to confirm")
    parser.add_argument("--cattle-scores", type=Path, required=True, help="Written by app_scores")
    parser.add_argument("--cattle-similarities", type=Path, help="Crop by photograph, optional")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--either-side", action="store_true", help="Development only")
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--adapt", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", type=Path, required=True, help="Prefix of the score files")
    arguments = parser.parse_args()
    meta = json.loads(arguments.cattle_scores.with_suffix(".json").read_text())
    cattle = np.load(arguments.cattle_scores.with_suffix(".npz"))
    classes = cattle["classes"].tolist()
    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()),
        meta["video"],
        set(arguments.enrolled),
        either_side=arguments.either_side,
    )
    # The catalog lists photographs cow by cow, in the order they were confirmed.
    rows = sorted(rows, key=lambda row: row["cow"])
    images = [cv2.imread(str(arguments.manifest.parent / row["path"])) for row in rows]
    owners = np.array([row["cow"] for row in rows])
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    network = MiewidNetwork()
    network.load_state_dict(load_file(str(arguments.animal_weights)))
    network.to(device)
    if arguments.adapt:
        adapt(network, images, np.searchsorted(classes, owners), len(classes), device)
    network.eval()
    similarity = describe(
        network, tracked_crops(meta["track"], arguments.frames), device
    ) @ describe(network, images, device).T

    def write(name, scores):
        path = arguments.output.with_name(f"{arguments.output.name}-{name}")
        np.savez(path.with_suffix(".npz"), scores=scores, classes=np.array(classes))
        path.with_suffix(".json").write_text(json.dumps(meta | {"animal": name}) + "\n")

    alone = nearest(similarity, owners, classes)
    write("animal", alone)
    write("kinds", (cattle["scores"] + alone) / 2)
    if arguments.cattle_similarities:
        mixed = (np.load(arguments.cattle_similarities) + similarity) / 2
        write("mixed", nearest(mixed, owners, classes))


if __name__ == "__main__":
    main()
