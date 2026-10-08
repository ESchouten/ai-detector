"""How many annotated animals the application's detector and tracker find.

Counts tracked boxes written by app_track against the publisher's boxes: who
was located, whose box was fit to be evidence, and how the tracks hold together.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app_policy import Rules, fit_crops
from ethz import DISPUTED, frame_labels
from video_eval import associate


def measure(track, frames_root, labels_root, ignored):
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
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results = {}
    for path in arguments.tracks:
        result = measure(
            json.loads(path.read_text()),
            arguments.frames,
            arguments.labels,
            {*arguments.ignored, DISPUTED},
        )
        results[path.stem] = result
        print(
            f"{path.stem}: located {result['located']:.3f}, fit {result['fit']:.3f} of "
            f"{result['visible']}; {result['boxes_without_annotation']} of {result['boxes']} boxes "
            f"without annotation; {result['tracks_covering_two_animals']} of "
            f"{result['tracks_on_annotated_animals']} tracks cover two animals"
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
