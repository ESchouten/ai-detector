"""How well the MmCows pen's cows are told apart from the publisher's own boxes.

This sets the detector aside. One network of each kind is taught the enrolled
cows from confirmed photographs and then asked about the publisher's boxes of
a later half hour, cut by `mmcows.py photographs --between`. A crop is scored
as the application scores it. Counted are the crops that resemble their own
cow most, and those of them that score above what 99 in 100 crops of the
withheld cows reach, for lying cows and for cows on their feet.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import mmcows
from enroll import write_herd
from parts import KINDS, describe
from parts_compare import scores

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_model import choose_device, learn

# One network of each kind, numbered as the application numbers its own.
NETWORKS = {"cattle": 0, "animal": 3}


def rows_of(manifest):
    """A manifest's rows, with paths that hold wherever they are read from."""
    return [
        {**row, "path": str((manifest.parent / row["path"]).resolve())}
        for row in json.loads(manifest.read_text())
    ]


def describe_all(photographs, crops, weights, work):
    """Teach each kind on the enrolled cows and keep what it describes, as `parts` does."""
    data = work / "data"
    if not (data / "identities" / "catalog.json").exists():
        write_herd([row for row in photographs if row["cow"] in mmcows.ENROLLED], "/", data)
    store = IdentityCatalog(data / "identities")
    cows = [cow for cow in store.load().identities if cow.samples]
    samples = [(sample, index) for index, cow in enumerate(cows) for sample in cow.samples]
    np.save(work / "owners.npy", np.array([int(cows[index].name) for _, index in samples]))
    device = choose_device()
    for kind, seed in NETWORKS.items():
        target = work / f"{kind}-s{seed}.npz"
        if target.exists():
            continue
        network = KINDS[kind](len(cows))
        network.start(weights[kind])
        learn(store.read_image, samples, network, device, seed=seed)
        np.savez(
            target,
            photographs=describe(
                network, [store.read_image(sample) for sample, _ in samples], device
            ),
            crops=describe(network, [cv2.imread(row["path"]) for row in crops], device),
        )


def told_apart(similarity, cows, truth, chosen):
    """Among the chosen crops: the enrolled cows' that resemble themselves, and stand out."""
    enrolled = chosen & np.isin(truth, mmcows.ENROLLED)
    strangers = chosen & ~np.isin(truth, mmcows.ENROLLED)
    right = np.array(cows)[similarity.argmax(1)] == truth
    limit = float(np.quantile(similarity[strangers].max(1), 0.99))
    return {
        "crops_of_enrolled_cows": int(enrolled.sum()),
        "crops_of_withheld_cows": int(strangers.sum()),
        "resemble_their_own_cow_most": float(right[enrolled].mean()),
        "and_score_above_99_in_100_strangers": float(
            (right & (similarity.max(1) > limit))[enrolled].mean()
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photographs", type=Path, nargs="+", help="Manifests of photographs")
    parser.add_argument("--crops", type=Path, required=True, help="Manifest of the later boxes")
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--work", type=Path, required=True, help="Keeps what was described")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    photographs = [row for manifest in arguments.photographs for row in rows_of(manifest)]
    crops = rows_of(arguments.crops)
    arguments.work.mkdir(parents=True, exist_ok=True)
    describe_all(
        photographs,
        crops,
        {"cattle": arguments.herd_weights, "animal": arguments.animal_weights},
        arguments.work,
    )
    similarity, cows = scores(
        arguments.work, "+".join(f"{kind}:{seed}" for kind, seed in NETWORKS.items()) + "@share"
    )
    truth = np.array([row["cow"] for row in crops])
    bundle, _ = mmcows.archive(mmcows.LABELLED)
    doing = {cow: mmcows.behaviour(bundle, cow) for cow in sorted(set(truth.tolist()))}
    # A crop's file is named by its camera and the second it was taken.
    lying = np.array(
        [
            doing[row["cow"]][int(Path(row["path"]).stem.split("-")[1])] == mmcows.LYING
            for row in crops
        ]
    )
    result = {
        "photographs_of_enrolled_cows": sum(row["cow"] in mmcows.ENROLLED for row in photographs),
        "all": told_apart(similarity, cows, truth, np.ones(len(crops), dtype=bool)),
        "lying": told_apart(similarity, cows, truth, lying),
        "on_her_feet": told_apart(similarity, cows, truth, ~lying),
    }
    arguments.output.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
