"""Who another rule's event would be named after, simulated from an application run.

A rule that detects behaviour boxes the animal showing it: on the mounting
example the box is the mounting cow's own to within a few per cent. So the
publisher's box of one annotated animal stands in for an event's boxes, for
every stretch of `--seconds` in which she stays annotated. The names come
from the application run through the detector's own `NamedSightings`, as a
second rule on that camera would receive them.

Every other name on an event is judged by the publisher's boxes: that animal
was inside the framed one's box by the detector's own rule, she overlapped
it most of the time, or she was not there.
"""

import argparse
import json
import sys
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from ethz import DISPUTED, frame_labels

from aidetector.adapters.named_sightings import NamedSightings
from aidetector.domain.identity import Sighting, individuals_in_event
from aidetector.domain.models import (
    BoundingBox,
    DetectionEvent,
    IdentityMatch,
    Observation,
)

SOURCE = "evaluated-video"
START = datetime(2026, 1, 1)
# An animal overlaps the event when this share of her box lies in it.
OVERLAPPING = 0.1


def stretches(present, length):
    """Positions of consecutive, non-overlapping runs of `length` true values."""
    found, run = [], []
    for position, value in enumerate(present):
        run = [*run, position] if value else []
        if len(run) == length:
            found.append(run)
            run = []
    return found


def moment(seconds):
    return START + timedelta(seconds=seconds)


def observation(seconds, size, boxes):
    """Boxes as (name, x1, y1, x2, y2) on a picture of `size`; no name, no identity."""
    width, height = size
    return Observation(
        moment(seconds),
        np.broadcast_to(np.uint8(0), (height, width, 3)),
        {"animal": 1.0},
        tuple(
            BoundingBox(
                *(round(value) for value in box),
                identity=None if name is None else IdentityMatch(str(name), str(name)),
            )
            for name, *box in boxes
        ),
    )


def cows(matches):
    return {int(match.identity_id) for match in matches}


def framed(truth, seconds):
    """Events in the order they end: (positions, cow, her box at every position)."""
    events = []
    for cow in {cow for boxes in truth for cow, *_ in boxes} - {DISPUTED}:
        own = [next((box[1:] for box in boxes if box[0] == cow), None) for boxes in truth]
        events += [
            (positions, cow, own)
            for positions in stretches([box is not None for box in own], seconds + 1)
        ]
    return deque(sorted(events, key=lambda event: (event[0][-1], event[1])))


def simulate(run, frames, labels_root, seconds):
    """Counts per kind of framed animal: enrolled or stranger."""
    size, shown_size = run["boxes"][0]["frame_size"], run["boxes"][0]["app_size"]
    width, height = size
    truth = [frame_labels(labels_root, run["video"], frame["index"], *size) for frame in frames]
    shown = {frame["index"]: [] for frame in frames}
    for box, name in zip(run["boxes"], run["shown"], strict=True):
        shown[box["index"]].append((name, *box["app_box"]))
    events = framed(truth, seconds)
    application = NamedSightings()
    apart = application.apart.total_seconds()
    enrolled = set(run["enrolled"])
    counts = {"enrolled": Counter(), "stranger": Counter()}
    for frame in frames:
        now = frame["seconds"]
        application.record(SOURCE, observation(now, shown_size, shown[frame["index"]]))
        # An event is delivered once what was seen just after it has been recorded.
        while events and (
            frame is frames[-1] or frames[events[0][0][-1]]["seconds"] + apart <= now
        ):
            positions, cow, own = events.popleft()
            names = cows(
                application.named(
                    DetectionEvent(
                        SOURCE,
                        tuple(
                            observation(frames[position]["seconds"], size, [(None, *own[position])])
                            for position in positions
                        ),
                    )
                )
            )
            # The publisher's view of the same event and of everyone around it.
            moments = [
                (
                    moment(frames[position]["seconds"]),
                    [
                        (
                            own[position][0] / width,
                            own[position][1] / height,
                            own[position][2] / width,
                            own[position][3] / height,
                        )
                    ],
                )
                for position in positions
            ]
            around = [
                Sighting(
                    moment(frames[position]["seconds"]),
                    IdentityMatch(str(other), str(other)),
                    (x1 / width, y1 / height, x2 / width, y2 / height),
                )
                for position in range(max(0, positions[0] - 1), min(len(frames), positions[-1] + 2))
                for other, x1, y1, x2, y2 in truth[position]
                if other != cow
            ]
            inside = cows(individuals_in_event(moments, around, apart=apart))
            overlapping = cows(
                individuals_in_event(moments, around, inside=OVERLAPPING, seen=1, apart=apart)
            )
            others = names - {cow}
            count = counts["enrolled" if cow in enrolled else "stranger"]
            count["events"] += 1
            count["framed_animal_named"] += cow in names
            count["nobody_named"] += not names
            count["enrolled_animal_inside_her_box"] += bool(inside & enrolled)
            count["another_named_who_was_inside"] += bool(others & inside)
            count["another_named_who_overlapped"] += bool(others & overlapping - inside)
            count["another_named_who_was_not_there"] += bool(others - overlapping)
    return {kind: dict(count) for kind, count in counts.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--seconds", type=int, nargs="+", default=[5])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    run = json.loads(arguments.run.read_text())
    frames = json.loads((arguments.frames / "frames.json").read_text())["frames"]
    result = {
        "video": run["video"],
        "events_of_seconds": {
            str(seconds): simulate(run, frames, arguments.labels, seconds)
            for seconds in arguments.seconds
        },
    }
    text = json.dumps(result, indent=2)
    if arguments.output:
        arguments.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
