"""Lay out what `app_describe` kept of an application run as `parts` keeps a run.

An application run's networks can then be combined with networks that
`parts` taught on the same photographs and tracked boxes, or compared with
them, by `parts_compare`: its cattle networks become `cattle-s0` and on, its
second kind `animal-s<n>`.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def members(saved):
    """Each network's descriptions of the photographs and the crops, cattle networks first."""
    cattle, animal = saved["parts"].tolist()
    count = cattle // 256
    for member in range(count):
        part = slice(member * 256, (member + 1) * 256)
        # A kind's part was scaled so that its dot product is the mean over its networks.
        yield (
            f"cattle-s{member}",
            saved["photographs"][:, part].astype(np.float32) * np.sqrt(count),
            saved["crops"][:, part].astype(np.float32) * np.sqrt(count),
        )
    yield f"animal-s{count}", saved["photographs"][:, cattle:], saved["crops"][:, cattle:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("described", type=Path, help="Written by app_describe")
    parser.add_argument("--track", type=Path, required=True, help="Written by app_track")
    parser.add_argument("--output", type=Path, required=True, help="The run's folder for parts")
    arguments = parser.parse_args()
    saved = np.load(arguments.described)
    arguments.output.mkdir(parents=True, exist_ok=True)
    np.save(arguments.output / "owners.npy", saved["owners"])
    for name, photographs, crops in members(saved):
        np.savez(arguments.output / f"{name}.npz", photographs=photographs, crops=crops)
    owners = saved["owners"].tolist()
    (arguments.output / "run.json").write_text(
        json.dumps(
            {
                "video": json.loads(arguments.track.read_text())["video"],
                "track": str(arguments.track),
                "enrolled": saved["classes"].tolist(),
                "either_side": False,
                "photographs_per_cow": {str(cow): owners.count(cow) for cow in sorted(set(owners))},
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
