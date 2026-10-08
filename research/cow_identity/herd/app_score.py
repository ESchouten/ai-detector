"""Score the names an application run showed, and check them against a replay.

The run recorded the similarities behind every decision. Replaying the same
rules over those numbers must give the names the application showed; the
replay then also tells where each visible animal was lost.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from app_policy import Rules, funnel, name_crops
from ethz import DISPUTED, frame_labels
from video_eval import associate, tally


def load_run(path):
    run = json.loads(Path(path).read_text())
    saved = np.load(Path(path).with_suffix(".npz"))
    classes = saved["classes"].tolist()
    # No cow of another farm competes in the application: an empty last column.
    scores = np.concatenate(
        [saved["scores"], np.full((len(saved["scores"]), 1), -1.0)], axis=1
    )
    return run, classes, scores


def preset_rules(preset):
    identity = preset["identity"]
    return Rules(
        identity["min_similarity"],
        identity["min_margin"],
        identity["min_observations"],
        identity["hold"],
        identity["min_crop_size"],
        identity["max_overlap"],
        whole_animal=True,
        min_similarity_infrared=identity["min_similarity_infrared"],
    )


def score_run(path, frames_directory, labels_root, withheld, ignored=frozenset()):
    run, classes, scores = load_run(path)
    boxes = run["boxes"]
    all_frames = [
        frame["index"]
        for frame in json.loads((Path(frames_directory) / "frames.json").read_text())["frames"]
    ]
    width, height = boxes[0]["frame_size"]
    partner, visible, located, around = associate(
        boxes,
        all_frames,
        lambda index: frame_labels(labels_root, run["video"], index, width, height),
    )
    enrolled = set(classes)
    unexpected = set(visible) - enrolled - set(withheld) - set(ignored) - {DISPUTED}
    if unexpected:
        raise ValueError(f"Animals that are neither enrolled nor withheld: {unexpected}")
    result = tally(
        run["shown"], partner, visible, located, around, enrolled, {*ignored, DISPUTED}
    )
    replay_boxes = [
        {**box, "box": box["app_box"], "frame_size": box["app_size"]} for box in boxes
    ]
    occupied = {box["seconds"] for box in boxes}
    replayed, stages = name_crops(
        replay_boxes,
        scores,
        classes,
        preset_rules(run["preset"]),
        [float(step) for step in range(run["frames"]) if float(step) not in occupied],
    )
    result["replay_matches_application"] = replayed == run["shown"]
    result["replay_differences"] = sum(
        first != second for first, second in zip(replayed, run["shown"], strict=True)
    )
    result["stages"] = funnel(stages, partner, visible, located, enrolled)
    result["stages_per_cow"] = {
        str(cow): funnel(stages, partner, visible, located, {cow})
        for cow in sorted(enrolled)
        if visible[cow]
    }
    names_elsewhere = {}
    for name, cow in zip(run["shown"], partner, strict=True):
        if name is not None and cow != name and cow not in ignored and cow != DISPUTED:
            key = f"{'unannotated' if cow is None else cow} shown as {name}"
            names_elsewhere[key] = names_elsewhere.get(key, 0) + 1
    result["names_on_other_animals"] = names_elsewhere
    tracks = {}
    for box, cow in zip(boxes, partner, strict=True):
        if cow is not None and cow not in ignored and cow != DISPUTED:
            tracks.setdefault(box["track"], set()).add(cow)
    result["tracking"] = {
        "tracks_on_annotated_animals": len(tracks),
        "tracks_covering_two_animals": sum(len(cows) > 1 for cows in tracks.values()),
    }
    for key in (
        "video",
        "enrolled",
        "confirmed_photographs",
        "confirmations",
        "photographs_per_cow",
        "latest_photograph",
        "device",
        "learning_seconds",
        "frames",
        "seconds_per_frame",
        "detector_weights_sha256",
        "herd_weights_sha256",
        "animal_weights_sha256",
    ):
        result[key] = run[key]
    result["withheld"] = sorted(withheld)
    result["ignored"] = sorted(ignored)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--withheld", type=int, nargs="*", default=[])
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = score_run(
        arguments.run,
        arguments.frames,
        arguments.labels,
        set(arguments.withheld),
        set(arguments.ignored),
    )
    print(json.dumps({key: value for key, value in result.items() if key != "per_cow"}, indent=1))
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
