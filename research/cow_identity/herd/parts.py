"""Teach one kind of network on a run's confirmed photographs and keep what it describes.

The application teaches several networks and keeps only their joint scores.
Kept apart, one network's descriptions of the photographs and of the tracked
crops can be combined with others afterwards: networks started from other
weights, more or fewer of a kind, fewer photographs to compare with.
`parts_compare` does that without running a network again.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from app_scores import tracked_crops
from enroll import write_herd
from ethz import confirmed_before

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_model import (
    AnimalNetwork,
    CattleNetwork,
    choose_device,
    learn,
    to_tensor,
)

KINDS = {"cattle": CattleNetwork, "animal": AnimalNetwork}


def fewer_photographs(rows, count):
    """At most `count` photographs per cow, drawn at random and so spread over the same days."""
    generator = np.random.default_rng(count)
    kept = []
    for cow in sorted({row["cow"] for row in rows}):
        own = [row for row in rows if row["cow"] == cow]
        chosen = generator.choice(len(own), min(count, len(own)), replace=False)
        kept += [own[position] for position in sorted(chosen)]
    return kept


def describe(network, pictures, device):
    described = []
    with torch.inference_mode():
        for first in range(0, len(pictures), 64):
            pixels = to_tensor([network.fit(picture) for picture in pictures[first : first + 64]])
            described.append(network.describe(pixels.to(device)).cpu().numpy())
    return np.concatenate(described).astype(np.float16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Publisher crops to confirm")
    parser.add_argument("--track", type=Path, required=True, help="Written by app_track")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--either-side", action="store_true", help="Development only")
    parser.add_argument("--photographs", type=int, help="At most this many per cow")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--weights", type=Path, required=True, help="What the network starts from")
    parser.add_argument("--label", required=True, help="Names those weights in the file names")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--data", type=Path, required=True, help="Data folder, written if empty")
    parser.add_argument("--output", type=Path, required=True, help="This run's descriptions")
    arguments = parser.parse_args()
    track = json.loads(arguments.track.read_text())
    if not (arguments.data / "identities" / "catalog.json").exists():
        rows = confirmed_before(
            json.loads(arguments.manifest.read_text()),
            track["video"],
            set(arguments.enrolled),
            either_side=arguments.either_side,
        )
        if arguments.photographs:
            rows = fewer_photographs(rows, arguments.photographs)
        write_herd(rows, arguments.manifest.parent, arguments.data)
    store = IdentityCatalog(arguments.data / "identities")
    cows = [cow for cow in store.load().identities if cow.samples]
    samples = [(sample, index) for index, cow in enumerate(cows) for sample in cow.samples]
    arguments.output.mkdir(parents=True, exist_ok=True)
    np.save(
        arguments.output / "owners.npy", np.array([int(cows[index].name) for _, index in samples])
    )
    (arguments.output / "run.json").write_text(
        json.dumps(
            {
                "video": track["video"],
                "track": str(arguments.track),
                "enrolled": sorted(arguments.enrolled),
                "either_side": arguments.either_side,
                "photographs_per_cow": {cow.name: len(cow.samples) for cow in cows},
            }
        )
        + "\n"
    )
    device = choose_device()
    photographs = [store.read_image(sample) for sample, _ in samples]
    crops = tracked_crops(arguments.track, arguments.frames)
    for seed in arguments.seeds:
        target = arguments.output / f"{arguments.label}-s{seed}.npz"
        if target.exists():
            continue
        started = time.perf_counter()
        network = KINDS[arguments.kind](len(cows))
        network.start(arguments.weights)
        learn(store.read_image, samples, network, device, seed=seed)
        np.savez(
            target,
            photographs=describe(network, photographs, device),
            crops=describe(network, crops, device),
        )
        print(
            f"{arguments.output.name} {arguments.label} seed {seed}: {len(samples)} photographs, "
            f"{time.perf_counter() - started:.0f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
