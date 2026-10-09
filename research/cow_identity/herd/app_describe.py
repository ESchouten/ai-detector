"""Describe an application run's tracked crops again, with the networks that run taught.

A run keeps the names it showed and the scores behind them, not what the
networks described. With the descriptions the same crops can be scored another
way, or compared with fewer photographs, without running a network again;
`rescore` does that. The data folder is the run's own, so the herd model in it
is reloaded and not taught anew.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_gallery import prepare_herd
from aidetector.adapters.media.images import shrink_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="The run's data folder")
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    started = time.perf_counter()
    run = json.loads(arguments.run.read_text())
    store = IdentityCatalog(arguments.data / "identities")
    gallery = prepare_herd(
        store.load(),
        store=store,
        cattle_start=arguments.herd_weights,
        animal_start=arguments.animal_weights,
        directory=arguments.data / "identities" / "herd",
    )
    files = {
        frame["index"]: frame["file"]
        for frame in json.loads((arguments.frames / "frames.json").read_text())["frames"]
    }
    by_frame = {}
    for position, box in enumerate(run["boxes"]):
        by_frame.setdefault(box["index"], []).append(position)
    described = np.zeros((len(run["boxes"]), gallery.vectors.shape[1]), np.float16)
    for index, positions in by_frame.items():
        image = shrink_image(
            cv2.imread(str(arguments.frames / files[index])),
            run["boxes"][positions[0]]["app_size"][0],
        )
        crops = []
        for position in positions:
            left, top, right, bottom = run["boxes"][position]["app_box"]
            crops.append(image[top:bottom, left:right])
        described[positions] = gallery.encoder.encode(crops)
    np.savez(
        arguments.output,
        crops=described,
        photographs=gallery.vectors.astype(np.float16),
        owners=np.array([int(name) for _, name in gallery.owners]),
        parts=np.array(gallery.parts),
    )
    print(
        f"{run['video']}: {len(described)} crops and {len(gallery.owners)} photographs "
        f"described in {time.perf_counter() - started:.0f}s"
    )


if __name__ == "__main__":
    main()
