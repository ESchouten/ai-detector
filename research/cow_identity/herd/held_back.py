"""Whether a herd's own confirmed photographs show that its cows can be told apart.

Each cow's latest fifth of photographs is held back, one cattle network is
taught the rest, and the held-back photographs are scored as the application
scores a crop. The share that resembles its own cow most needs no video and
no labels beyond the farmer's confirmations, so the application could work it
out when it learns a herd.
"""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

import mmcows  # registers the second farm's videos
from ethz import confirmed_before, crop_time
from parts import teach
from parts_compare import scores

HELD_BACK = 0.2


def split(rows):
    """Each cow's photographs in order of time: the earlier ones, and her latest fifth."""
    earlier, later = [], []
    for cow in sorted({row["cow"] for row in rows}):
        own = sorted((row for row in rows if row["cow"] == cow), key=crop_time)
        cut = round((1 - HELD_BACK) * len(own))
        earlier += own[:cut]
        later += own[cut:]
    return earlier, later


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Photographs to confirm")
    parser.add_argument("--video", required=True, help="The herd is the one confirmed for it")
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()), arguments.video, set(arguments.enrolled)
    )
    earlier, later = split(rows)
    with tempfile.TemporaryDirectory() as work:
        teach(
            earlier,
            arguments.manifest.parent,
            [arguments.manifest.parent / row["path"] for row in later],
            {"cattle": (0,)},
            {"cattle": arguments.herd_weights},
            Path(work),
        )
        similarity, names = scores(Path(work), "cattle:0@share")
    right = np.array(names)[similarity.argmax(1)] == np.array([row["cow"] for row in later])
    result = {
        "video": arguments.video,
        "photographs_taught": len(earlier),
        "photographs_held_back": len(later),
        "held_back_that_resemble_their_own_cow_most": float(right.mean()),
    }
    arguments.output.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
