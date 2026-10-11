"""Give every published picture one frame of the footage, in the order the pictures were taken.

`multicam_locate` keeps every frame that a picture fits closely. A picture
laid on the frame it was cut from differs from it by 5 to 8 grey levels; a
cow that stands still fits the frames beside it too, a little less closely,
and so do the pictures before and after hers. A cow's pictures are in the
order they were filmed, so their frames have to rise with them.

First each walk takes its pictures' own frames, as many as rise in order. A
picture that is left without one is then looked for in the frames between the
neighbours on either side of it, around where those lie, whether or not
anything was seen to move there. Last, each walk takes the most pictures on
their own frames, then the most pictures at all, in rising order.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

import multicam
from multicam_locate import CLOSE, SKIPPED, STEP, corners, details, difference, fitted

# A picture differs by less than this from the frame it was cut from.
OWN = 8
# How far around its neighbours a picture is looked for, in points of the frame.
AROUND = 250
ALL_DETAILS = cv2.SIFT_create()


def best(positions, own, count, cost):
    """Among chains: the most pictures on their own frames, then the most, then the closest."""
    positions = positions[own[positions] == own[positions].max()]
    positions = positions[count[positions] == count[positions].max()]
    return positions[cost[positions].argmin()]


def rising(nodes):
    """The nodes that rise in place and in time and give the most pictures their own frames.

    A node is (place in the walk, time, difference, entry). Among chains with as many
    pictures on their own frames, the one with the most pictures is taken, and among
    those the closest fits.
    """
    nodes = sorted(nodes, key=lambda node: node[:3])
    if not nodes:
        return []
    place = np.array([node[0] for node in nodes])
    time = np.array([node[1] for node in nodes])
    apart = np.array([node[2] for node in nodes])
    own, count, cost = (apart < OWN).astype(int), np.ones(len(nodes), dtype=int), apart.copy()
    before = np.full(len(nodes), -1)
    for position in range(len(nodes)):
        earlier = np.flatnonzero(
            (place[:position] < place[position]) & (time[:position] < time[position])
        )
        if len(earlier):
            last = best(earlier, own, count, cost)
            own[position] += own[last]
            count[position] += count[last]
            cost[position] += cost[last]
            before[position] = last
    position = best(np.arange(len(nodes)), own, count, cost)
    chosen = []
    while position >= 0:
        chosen.append(nodes[position])
        position = before[position]
    return chosen[::-1]


def gaps(walk, placed):
    """Runs of a walk's pictures without a frame, each with the placed picture before and after."""
    runs, run = [], []
    for position, file in enumerate(walk):
        if file in placed:
            if run:
                runs.append((run, walk[run[0] - 1] if run[0] else None, file))
            run = []
        else:
            run.append(position)
    if run:
        runs.append((run, walk[run[0] - 1] if run[0] else None, None))
    return [
        (run, placed.get(before), placed.get(after))
        for run, before, after in runs
        if before or after
    ]


def possible(run, before, after):
    """For each picture of a run, the clips and frames in which it can lie.

    Between two neighbours of one clip a picture lies about as far along as its place in
    the run. Beside one neighbour it lies at least its distance in frames away, and no
    more than the frames a walk may skip beyond that.
    """
    slack = SKIPPED * STEP
    frames = {}
    for offset, place in enumerate(run, start=1):
        if before and after and before["clip"] == after["clip"]:
            span = after["frame"] - before["frame"]
            expected = before["frame"] + round(span * offset / (len(run) + 1) / STEP) * STEP
            first = max(before["frame"] + STEP, expected - slack)
            last = min(after["frame"] - STEP, expected + slack)
            frames[place] = [(before["clip"], number) for number in range(first, last + 1, STEP)]
            continue
        frames[place] = []
        if before:
            first = before["frame"] + STEP * offset
            frames[place] += [
                (before["clip"], number) for number in range(first, first + slack + 1, STEP)
            ]
        if after:
            last = after["frame"] - STEP * (len(run) - offset + 1)
            frames[place] += [
                (after["clip"], number) for number in range(max(0, last - slack), last + 1, STEP)
            ]
    return frames


def region(neighbours, width, height):
    """The part of a frame around where a run's neighbours lie."""
    points = np.concatenate([np.array(neighbour["corners"]) for neighbour in neighbours])
    left, top = np.clip(points.min(0) - AROUND, 0, (width, height)).astype(int)
    right, bottom = np.clip(points.max(0) + AROUND, 0, (width, height)).astype(int)
    return int(left), int(top), int(right), int(bottom)


def fill(arguments):
    record = json.loads(arguments.located.read_text())
    walks = [
        walk["files"]
        for walk in multicam.walks(arguments.pictures, (record["day"],), multicam.COWS)
        if walk["camera"] == record["camera"]
    ]
    clips = multicam.clips(arguments.footage, record["day"], record["camera"])
    order = {clip.name: position for position, clip in enumerate(clips)}
    fits = defaultdict(list)
    for fit in record["fits"]:
        fits[fit["cow"], fit["picture"]].append(fit)

    def time(entry):
        """Later clips after earlier ones; no clip has ten million frames."""
        return order[entry["clip"]] * 10_000_000 + entry["frame"]

    nodes = {}
    wanted = defaultdict(lambda: defaultdict(list))
    for walk in walks:
        nodes[id(walk)] = [
            (place, time(fit), fit["difference"], fit)
            for place, file in enumerate(walk)
            for fit in fits[int(file.parent.name), file.name]
        ]
        sure = {
            walk[place]: entry
            for place, _, _, entry in rising([node for node in nodes[id(walk)] if node[2] < OWN])
        }
        for run, before, after in gaps(walk, sure):
            neighbours = [neighbour for neighbour in (before, after) if neighbour]
            for place, frames in possible(run, before, after).items():
                for clip, number in frames:
                    wanted[clip][number].append((walk, place, neighbours))
    kept = {}

    def described(file):
        if file not in kept:
            picture = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
            kept[file] = (picture, details(picture))
        return kept[file]

    for clip in clips:
        capture = cv2.VideoCapture(str(clip))
        for number in sorted(wanted[clip.name]):
            capture.set(cv2.CAP_PROP_POS_FRAMES, number)
            read, image = capture.read()
            if not read:
                continue
            grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            seen = {}
            for walk, place, neighbours in wanted[clip.name][number]:
                part = region(neighbours, grey.shape[1], grey.shape[0])
                if part not in seen:
                    left, top, right, bottom = part
                    points, told = details(grey[top:bottom, left:right], ALL_DETAILS)
                    seen[part] = (points + np.float32([left, top]), told)
                picture, own = described(walk[place])
                transform = fitted(own, seen[part])
                if transform is None:
                    continue
                apart = difference(grey, picture, transform)
                if apart < CLOSE:
                    entry = {
                        "cow": int(walk[place].parent.name),
                        "picture": walk[place].name,
                        "clip": clip.name,
                        "frame": number,
                        "corners": corners(transform, picture.shape[1], picture.shape[0]),
                        "difference": round(apart, 2),
                    }
                    nodes[id(walk)].append((place, time(entry), apart, entry))
    placed = {}
    for walk in walks:
        placed.update({walk[place]: entry for place, _, _, entry in rising(nodes[id(walk)])})
    pictures = [file for walk in walks for file in walk]
    arguments.output.write_text(
        json.dumps(
            {
                "day": record["day"],
                "camera": record["camera"],
                "frames_read": record["frames_read"],
                "pictures": len(pictures),
                "fitted": record["found"],
                "found": len(placed),
                "on_their_own_frame": sum(entry["difference"] < OWN for entry in placed.values()),
                "located": [placed[file] for file in pictures if file in placed],
            }
        )
        + "\n"
    )
    print(
        record["day"],
        record["camera"],
        len(placed),
        "of",
        len(pictures),
        "pictures placed;",
        record["found"],
        "fitted a frame",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("located", type=Path, help="Written by multicam_locate")
    parser.add_argument("pictures", type=Path, help="MultiCamCows2024Root")
    parser.add_argument("footage", type=Path, help="Written by multicam.py fetch")
    parser.add_argument("--output", type=Path, required=True)
    fill(parser.parse_args())


if __name__ == "__main__":
    main()
