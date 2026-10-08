"""Name tracked animals in one video from cached crop scores and score the names.

Boxes do not depend on the naming limits, so each crop is paired with the
publisher's boxes once; trying other limits then only recounts.
"""

import argparse
import json
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

import numpy as np

from ethz import DISPUTED, frame_labels
from matching import match, overlap
from policy import Limits, Namer
from video_score import lies_on, summarise, unpaired


def associate(crops, all_frames, labels):
    """Pair every crop with an annotated animal; count who was visible.

    Returns (cow per crop or None, Counter of visible cows, Counter of located
    cows, surroundings per crop): the annotated animal a crop lies on, if any,
    and every animal annotated in its frame.
    """
    by_frame = defaultdict(list)
    for position, crop in enumerate(crops):
        by_frame[crop["index"]].append(position)
    partner = [None] * len(crops)
    around = [(None, frozenset())] * len(crops)
    visible, located = Counter(), Counter()
    for index in all_frames:
        truth = labels(index)
        positions = by_frame.get(index, [])
        present = frozenset(cow for cow, *_ in truth)
        for cow, *_ in truth:
            visible[cow] += 1
        pairs = match([box[1:] for box in truth], [crops[p]["box"] for p in positions])
        for annotated, predicted in pairs:
            partner[positions[predicted]] = truth[annotated][0]
            located[truth[annotated][0]] += 1
        for position in positions:
            around[position] = (lies_on(crops[position]["box"], truth), present)
    return partner, visible, located, around


def crop_geometry(crops):
    """Per crop: shorter side, largest overlap with a neighbour, border contact."""
    by_frame = defaultdict(list)
    for position, crop in enumerate(crops):
        by_frame[crop["index"]].append(position)
    side = np.zeros(len(crops))
    crowding = np.zeros(len(crops))
    border = np.zeros(len(crops), dtype=bool)
    for positions in by_frame.values():
        boxes = np.array([crops[p]["box"] for p in positions], dtype=np.float64)
        shared = overlap(boxes, boxes)
        np.fill_diagonal(shared, 0.0)
        width, height = crops[positions[0]]["frame_size"]
        for row, position in enumerate(positions):
            left, top, right, bottom = boxes[row]
            side[position] = min(right - left, bottom - top)
            crowding[position] = shared[row].max() if len(positions) > 1 else 0.0
            border[position] = (
                left <= 2 or top <= 2 or right >= width - 2 or bottom >= height - 2
            )
    return side, crowding, border


def name_crops(crops, scores, classes, limits, fit):
    """The name the policy shows on every crop, in the order of `crops`."""
    by_frame = defaultdict(list)
    for position, crop in enumerate(crops):
        by_frame[crop["index"]].append(position)
    namer = Namer(classes, limits)
    names = [None] * len(crops)
    for index in sorted(by_frame):
        positions = by_frame[index]
        shown = namer.update(
            crops[positions[0]]["seconds"],
            [
                (crops[position]["track"], scores[position] if fit[position] else None)
                for position in positions
            ],
        )
        for position, name in zip(positions, shown, strict=True):
            names[position] = name
    return names


def tally(names, partner, visible, located, around, enrolled, ignored):
    counts = Counter()
    per_cow = defaultdict(Counter)
    for cow, seen in visible.items():
        if cow in ignored:
            continue
        kind = "enrolled" if cow in enrolled else "withheld"
        counts[f"visible_{kind}"] += seen
        counts[f"located_{kind}"] += located[cow]
        per_cow[cow]["visible"] = seen
        per_cow[cow]["located"] = located[cow]
    for name, cow, (nearest, present) in zip(names, partner, around, strict=True):
        if name is None or cow in ignored:
            continue
        if cow is None:
            if nearest not in ignored:
                counts["named_unannotated"] += 1
                counts[unpaired(name, nearest, present, enrolled)] += 1
        elif cow not in enrolled:
            counts["named_withheld"] += 1
            per_cow[cow]["named"] += 1
        elif cow == name:
            counts["correct"] += 1
            per_cow[cow]["correct"] += 1
        else:
            counts["wrong_enrolled"] += 1
            per_cow[cow]["wrong"] += 1
    result = summarise(counts)
    result["per_cow"] = {str(cow): dict(values) for cow, values in sorted(per_cow.items())}
    return result


def load(scores_path, crops_directory, frames_directory, labels_root):
    saved = np.load(scores_path)
    classes = saved["classes"].tolist()
    video = json.loads(Path(scores_path).with_suffix(".json").read_text())["video"]
    crops = json.loads((Path(crops_directory) / "crops.json").read_text())
    all_frames = [
        frame["index"]
        for frame in json.loads((Path(frames_directory) / "frames.json").read_text())["frames"]
    ]
    width, height = crops[0]["frame_size"]
    cache = {}

    def labels(index):
        if index not in cache:
            cache[index] = frame_labels(labels_root, video, index, width, height)
        return cache[index]

    partner, visible, located, around = associate(crops, all_frames, labels)
    return {
        "video": video,
        "crops": crops,
        "classes": classes,
        "scores": np.concatenate([saved["scores"], saved["rival"][:, None]], axis=1),
        "partner": partner,
        "visible": visible,
        "located": located,
        "around": around,
        "geometry": crop_geometry(crops),
    }


def evaluate(data, limits, ignored=frozenset(), min_side=0, max_crowding=1.0, allow_border=True):
    ignored = {*ignored, DISPUTED}
    side, crowding, border = data["geometry"]
    fit = (side >= min_side) & (crowding <= max_crowding) & (allow_border | ~border)
    names = name_crops(data["crops"], data["scores"], [*data["classes"], None], limits, fit)
    result = tally(
        names,
        data["partner"],
        data["visible"],
        data["located"],
        data["around"],
        set(data["classes"]),
        ignored,
    )
    result["fit_crops"] = int(fit.sum())
    result["crops"] = len(fit)
    return result


def describe(result):
    def show(value):
        return "  n/a " if value is None else f"{value:.4f}"

    return (
        f"coverage {show(result['coverage'])} precision {show(result['precision'])} "
        f"(conservative {show(result['precision_conservative'])}) "
        f"withheld named {show(result['withheld_named'])} | "
        f"correct {result['correct']} wrong {result['wrong_enrolled']} "
        f"withheld {result['named_withheld']}/{result['visible_withheld']} "
        f"unannotated {result['named_unannotated']}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, help="npz written by video_identify")
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument("--floor", type=float, nargs="+", required=True)
    parser.add_argument("--margin", type=float, nargs="+", required=True)
    parser.add_argument("--observations", type=int, nargs="+", default=[3])
    parser.add_argument("--memory", type=float, nargs="+", default=[0.5])
    parser.add_argument("--min-side", type=float, default=0)
    parser.add_argument("--max-crowding", type=float, default=1.0)
    parser.add_argument("--no-border", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    data = load(arguments.scores, arguments.crops, arguments.frames, arguments.labels)
    results = []
    for floor, margin, observations, memory in product(
        arguments.floor, arguments.margin, arguments.observations, arguments.memory
    ):
        limits = Limits(floor, margin, observations, memory)
        result = evaluate(
            data,
            limits,
            set(arguments.ignored),
            arguments.min_side,
            arguments.max_crowding,
            not arguments.no_border,
        )
        result["limits"] = limits.__dict__
        results.append(result)
        print(
            f"floor {floor:.2f} margin {margin:.2f} n {observations} memory {memory:.1f}: "
            + describe(result),
            flush=True,
        )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
