"""Teach a herd model with the application's code and score cached boxes with it.

Together with the tracked boxes this is everything the application's identity
rules see, so any choice of rules can be replayed exactly without a model.
"""

import argparse
import json
import pickle
import time
from functools import partial
from pathlib import Path

import cv2
import numpy as np

from app_run import digest, identity_scores, taught_cows
from enroll import write_herd
from ethz import confirmed_before
from video_identify import fewer_confirmations

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_gallery import MEMBERS, prepare_herd
from aidetector.adapters.media.images import shrink_image


def tracked_crops(track_path, frames):
    """Every tracked box cut from its frame as the application cuts it.

    Decoding the frames takes longer than describing the crops, so the crops
    are kept beside the track and reused for every herd model tried on it.
    """
    kept = Path(track_path).with_suffix(".crops.pkl")
    if kept.exists():
        return pickle.loads(kept.read_bytes())
    track = json.loads(Path(track_path).read_text())
    by_file = {}
    for position, box in enumerate(track["boxes"]):
        by_file.setdefault(box["file"], []).append(position)
    crops = [None] * len(track["boxes"])
    for file, positions in by_file.items():
        image = shrink_image(
            cv2.imread(str(Path(frames) / file)), track["boxes"][positions[0]]["app_size"][0]
        )
        for position in positions:
            left, top, right, bottom = track["boxes"][position]["app_box"]
            crops[position] = image[top:bottom, left:right].copy()
    kept.write_bytes(pickle.dumps(crops))
    return crops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Publisher crops to confirm")
    parser.add_argument("--track", type=Path, required=True, help="Written by app_track")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--either-side", action="store_true", help="Development only")
    parser.add_argument("--confirmations", type=int)
    parser.add_argument("--members", type=int, default=MEMBERS)
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--data", type=Path, required=True, help="Empty data folder")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    track = json.loads(arguments.track.read_text())
    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()),
        track["video"],
        set(arguments.enrolled),
        either_side=arguments.either_side,
    )
    if arguments.confirmations:
        rows = fewer_confirmations(rows, arguments.confirmations)
    identities = write_herd(rows, arguments.manifest.parent, arguments.data)
    cow_of = {identity: cow for cow, identity in identities.items()}
    store = IdentityCatalog(arguments.data / "identities")
    started = time.perf_counter()
    gallery = partial(
        prepare_herd,
        store=store,
        cattle_start=arguments.herd_weights,
        animal_start=arguments.animal_weights,
        directory=arguments.data / "identities" / "herd",
        members=arguments.members,
    )(store.load())
    learning_seconds = time.perf_counter() - started
    classes = taught_cows(gallery, cow_of)
    crops = tracked_crops(arguments.track, arguments.frames)
    # The application describes the boxes of one frame together.
    by_frame = {}
    for position, box in enumerate(track["boxes"]):
        by_frame.setdefault(box["index"], []).append(position)
    scores = np.zeros((len(crops), len(classes)), dtype=np.float32)
    for positions in by_frame.values():
        scores[positions] = identity_scores(gallery, [crops[position] for position in positions])
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        arguments.output.with_suffix(".npz"),
        scores=scores,
        classes=np.array(classes),
    )
    arguments.output.with_suffix(".json").write_text(
        json.dumps(
            {
                "video": track["video"],
                "track": str(arguments.track),
                "enrolled": sorted(arguments.enrolled),
                "either_side": arguments.either_side,
                "members": arguments.members,
                "confirmed_photographs": len(rows),
                "confirmations": len({(row["cow"], row["clip"]) for row in rows}),
                "photographs_per_cow": {
                    str(cow): sum(row["cow"] == cow for row in rows) for cow in classes
                },
                "latest_photograph": max(row["date"] + row["time"] for row in rows),
                "herd_weights_sha256": digest(arguments.herd_weights),
                "animal_weights_sha256": digest(arguments.animal_weights),
                "device": gallery.encoder.device,
                "learning_seconds": learning_seconds,
            }
        )
        + "\n"
    )
    print(
        f"{track['video']}: {len(rows)} photographs of {len(classes)} cows, "
        f"{arguments.members} members, learning {learning_seconds:.0f}s"
    )


if __name__ == "__main__":
    main()
