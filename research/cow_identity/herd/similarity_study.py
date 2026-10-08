"""Which similarity tells a confirmed cow from a stranger, measured on taught models.

A taught network offers two things to compare a crop with: the direction it
learned for every cow, and its descriptions of that cow's own photographs. This
study scores development crops both ways, with one to all of the cattle
networks, with the animal network, and with both kinds as the application
combines them. It asks how many crops of confirmed cows pass a limit that lets
through one in a hundred, or in a thousand, crops of left-out cows. One limit
has to serve every herd, so the limit is also set once for all runs together.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file

from app_policy import Rules, fit_crops
from app_scores import tracked_crops
from tune import FINAL_WITHHELD, load_run

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_model import AnimalNetwork, CattleNetwork, to_tensor


def describe(data, crops, device):
    """Every network's description of the confirmed photographs and the tracked crops."""
    store = IdentityCatalog(Path(data) / "identities")
    cows = [cow for cow in store.load().identities if cow.samples]
    photographs = [store.read_image(sample) for cow in cows for sample in cow.samples]
    folder = Path(data) / "identities" / "herd"

    def taught(kind, file):
        network = kind(len(cows))
        network.load_state_dict(load_file(str(file)))
        return network.eval().requires_grad_(False).to(device)

    def described(network, images):
        batches = []
        for first in range(0, len(images), 64):
            pixels = to_tensor([network.fit(image) for image in images[first : first + 64]])
            with torch.inference_mode():
                batches.append(network.describe(pixels.to(device)).cpu().numpy())
        return np.concatenate(batches)

    networks = [
        taught(CattleNetwork, file) for file in sorted(folder.glob("herd-cattle-*.safetensors"))
    ]
    networks.append(taught(AnimalNetwork, folder / "herd-animal.safetensors"))
    return {
        "owners": np.array([int(cow.name) for cow in cows for _ in cow.samples]),
        "networks": [
            {
                "photographs": described(network, photographs),
                "crops": described(network, crops),
                "directions": torch.nn.functional.normalize(network.directions, dim=1)
                .cpu()
                .numpy(),
            }
            for network in networks
        ],
    }


def similarities(described, classes):
    """One (crop, cow) matrix per way of scoring."""
    *cattle, animal = described["networks"]
    owners = described["owners"]

    def nearest(to_photographs, count):
        return np.stack(
            [
                np.sort(to_photographs[:, owners == cow], axis=1)[:, -count:].mean(1)
                for cow in classes
            ],
            1,
        )

    def mean(networks, reference):
        return np.mean([network["crops"] @ network[reference].T for network in networks], 0)

    scores = {}
    for members in range(1, len(cattle) + 1):
        label = f"{members} cattle network{'s' if members > 1 else ''}"
        scores[f"directions, {label}"] = mean(cattle[:members], "directions")
        for count in (1, 2, 3, 5):
            scores[f"nearest {count}, {label}"] = nearest(
                mean(cattle[:members], "photographs"), count
            )
    scores["directions, animal network"] = mean([animal], "directions")
    scores["nearest 2, animal network"] = nearest(mean([animal], "photographs"), 2)
    scores["nearest 2, both kinds"] = nearest(
        (mean(cattle, "photographs") + mean([animal], "photographs")) / 2, 2
    )
    return scores


def passing(runs):
    """Share of confirmed cows' crops above the limit that strangers pass at a given rate."""
    result = {}
    for rate in (0.01, 0.001):
        limits = [float(np.quantile(strangers, 1 - rate)) for _, strangers in runs]
        shared = max(limits)
        result[f"strangers passing {rate}"] = {
            "own limit": [
                float(np.mean(known > limit)) for (known, _), limit in zip(runs, limits, strict=True)
            ],
            "one limit": [float(np.mean(known > shared)) for known, _ in runs],
            "limit": shared,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, nargs="+", help="Written by app_scores")
    parser.add_argument("--data", type=Path, nargs="+", required=True, help="Their data folders")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    samples = {}
    for scores_path, data in zip(arguments.scores, arguments.data, strict=True):
        run = load_run(scores_path, arguments.frames, arguments.labels)
        described = describe(
            data, tracked_crops(run["meta"]["track"], arguments.frames / run["video"]), device
        )
        classes = run["classes"]
        fit = np.array(fit_crops(run["boxes"], Rules(0, 0, min_crop_size=32, whole_animal=True)))
        partner = np.array([-99 if cow is None else cow for cow in run["partner"]])
        known = np.isin(partner, classes) & fit
        strangers = ~np.isin(partner, [*classes, *FINAL_WITHHELD, -99, -1]) & fit
        truth = np.array([classes.index(cow) if cow in classes else -1 for cow in partner])
        for name, scores in similarities(described, classes).items():
            best, chosen = scores.max(1), scores.argmax(1)
            # A crop that resembles another cow most can never be named rightly.
            samples.setdefault(name, []).append(
                (np.where(chosen[known] == truth[known], best[known], -1.0), best[strangers])
            )
        print(run["name"], "described", flush=True)
    summary = {
        "runs": [path.name for path in arguments.scores],
        "scores": {name: passing(runs) for name, runs in samples.items()},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(summary, indent=1) + "\n")
    for name, measured in summary["scores"].items():
        row = measured["strangers passing 0.01"]
        print(
            f"{name}: {min(row['own limit']):.2f}-{max(row['own limit']):.2f} with each run's own limit, "
            f"{min(row['one limit']):.2f}-{max(row['one limit']):.2f} with one limit ({row['limit']:.3f})"
        )


if __name__ == "__main__":
    main()
