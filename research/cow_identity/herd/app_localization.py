"""How many annotated animals the application's detector and tracker find.

Counts tracked boxes written by app_track against the publisher's boxes: who
was located, whose box was fit to be evidence, and how the tracks hold together.
It also counts the appearances that could carry a name if every fit crop were
recognised at once: a name needs the preset's number of fit pictures in a row
and is dropped when a box stops being fit, so an animal that is in view for a
few seconds is named late and loses the name as she leaves.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app_policy import Rules, fit_crops
from ethz import DISPUTED, frame_labels
from video_eval import associate


def nameable(boxes, fit, needed, kept_unfit=0):
    """Which boxes could carry a name, were every fit crop recognised at once.

    A track is named from its `needed`-th fit picture in a row. A box that is not fit ends
    the name, unless it comes within `kept_unfit` seconds of the track's last fit picture.
    """
    named = [False] * len(boxes)
    tracks = defaultdict(list)
    for position, box in enumerate(boxes):
        tracks[box["track"]].append(position)
    for positions in tracks.values():
        run, confirmed, whole = 0, False, None
        for position in sorted(positions, key=lambda at: boxes[at]["seconds"]):
            if fit[position]:
                run += 1
                confirmed = confirmed or run >= needed
                whole = boxes[position]["seconds"]
            else:
                run = 0
                confirmed = confirmed and boxes[position]["seconds"] - whole <= kept_unfit
            named[position] = confirmed
    return named


def measure(track, frames_root, labels_root, ignored, kept_unfit):
    boxes = track["boxes"]
    video = track["video"]
    frames = [
        frame["index"]
        for frame in json.loads((Path(frames_root) / video / "frames.json").read_text())["frames"]
    ]
    width, height = boxes[0]["frame_size"]
    partner, visible, located, _ = associate(
        boxes, frames, lambda index: frame_labels(labels_root, video, index, width, height)
    )
    fit = fit_crops(
        [{**box, "box": box["app_box"], "frame_size": box["app_size"]} for box in boxes],
        Rules(0, 0, min_crop_size=32, whole_animal=True),
    )
    usable = Counter(cow for cow, good in zip(partner, fit, strict=True) if good)
    needed = track["preset"]["identity"]["min_observations"]
    could = Counter(
        cow
        for cow, named in zip(partner, nameable(boxes, fit, needed, kept_unfit), strict=True)
        if named
    )
    animals = defaultdict(set)
    for box, cow in zip(boxes, partner, strict=True):
        if cow is not None and cow not in ignored:
            animals[box["track"]].add(cow)
    cows = sorted(cow for cow in visible if cow not in ignored)
    seen = sum(visible[cow] for cow in cows)
    return {
        "video": video,
        "detector_weights_sha256": track["detector_weights_sha256"],
        "yolo": track["preset"]["yolo"],
        "visible": seen,
        "located": sum(located[cow] for cow in cows) / seen,
        "fit": sum(usable[cow] for cow in cows) / seen,
        "could_carry_a_name": sum(could[cow] for cow in cows) / seen,
        "boxes": len(boxes),
        "boxes_without_annotation": sum(cow is None for cow in partner),
        "tracks_on_annotated_animals": len(animals),
        "tracks_covering_two_animals": sum(len(found) > 1 for found in animals.values()),
        "detect_seconds": track["detect_seconds"],
        "per_cow": {
            str(cow): {"visible": visible[cow], "located": located[cow], "fit": usable[cow]}
            for cow in cows
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tracks", type=Path, nargs="+", help="Written by app_track")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument(
        "--kept-unfit",
        type=float,
        default=0,
        help="Seconds a name is taken to outlast a track's last fit picture; none, as shipped",
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results = {}
    for path in arguments.tracks:
        result = measure(
            json.loads(path.read_text()),
            arguments.frames,
            arguments.labels,
            {*arguments.ignored, DISPUTED},
            arguments.kept_unfit,
        )
        results[path.stem] = result
        print(
            f"{path.stem}: located {result['located']:.3f}, fit {result['fit']:.3f}, could carry "
            f"a name {result['could_carry_a_name']:.3f} of {result['visible']}; "
            f"{result['boxes_without_annotation']} of {result['boxes']} boxes "
            f"without annotation; {result['tracks_covering_two_animals']} of "
            f"{result['tracks_on_annotated_animals']} tracks cover two animals"
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
