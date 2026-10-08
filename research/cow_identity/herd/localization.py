"""Localization and tracking measured against publisher boxes, without names.

Recall is the share of annotated animals that a predicted box covers at an
overlap of 0.5 or more. The publisher does not annotate every visible animal,
so predictions without a partner are counted but not called false.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from ethz import frame_labels
from matching import match


def measure(detections, labels_root, width=2560, height=1440):
    video = detections["video"]
    annotated = matched = unmatched = 0
    per_cow = defaultdict(lambda: [0, 0])
    per_track = defaultdict(Counter)
    last_track = {}
    switches = 0
    untracked = 0
    for frame in detections["frames"]:
        truth = frame_labels(labels_root, video, frame["index"], width, height)
        boxes = frame["boxes"]
        pairs = match([box[1:] for box in truth], [box["box"] for box in boxes])
        annotated += len(truth)
        matched += len(pairs)
        unmatched += len(boxes) - len(pairs)
        for cow, *_ in truth:
            per_cow[cow][0] += 1
        for truth_index, box_index in pairs:
            cow = truth[truth_index][0]
            per_cow[cow][1] += 1
            track = boxes[box_index]["track"]
            if track is None:
                untracked += 1
                continue
            per_track[track][cow] += 1
            if cow in last_track and last_track[cow] != track:
                switches += 1
            last_track[cow] = track
    mixed = sum(1 for cows in per_track.values() if len(cows) > 1)
    impure = sum(sum(cows.values()) - max(cows.values()) for cows in per_track.values())
    return {
        "video": video,
        "frames": len(detections["frames"]),
        "annotated": annotated,
        "matched": matched,
        "recall": matched / annotated,
        "unmatched_predictions": unmatched,
        "matched_without_track": untracked,
        "tracks": len(per_track),
        "tracks_covering_two_cows": mixed,
        "observations_off_track_majority": impure,
        "track_changes_per_cow": switches,
        "per_cow": {
            str(cow): {"annotated": seen, "matched": found, "recall": found / seen}
            for cow, (seen, found) in sorted(per_cow.items())
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detections", type=Path, nargs="+")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    results = [
        measure(json.loads(path.read_text()), arguments.labels)
        for path in arguments.detections
    ]
    for result in results:
        print(json.dumps({k: v for k, v in result.items() if k != "per_cow"}))
        print("  per cow recall:", {c: round(v["recall"], 2) for c, v in result["per_cow"].items()})
    if arguments.output:
        arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
