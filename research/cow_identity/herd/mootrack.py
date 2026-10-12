"""A ceiling camera where cows stay: what the application finds in MooTrack360's pictures.

MooTrack360 (https://zenodo.org/records/20287681, CC BY-NC-SA 4.0) films two
commercial Danish barns with sixteen fisheye cameras in the ceiling, 4.0 to
5.6 m above cubicles, feed fences and milking robots. In 1,500 pictures of forty
days, around the clock, its publisher drew a box around every cow in each
camera's own part of the barn and says whether she stands or lies. It says of
no cow who she is, so this measures what comes before a name: whether the
application's detector and tracker find a cow, and whether her box is fit to
be evidence.

A picture stands still, so it is shown to a tracker that has seen nothing
before. Such a tracker follows at once whatever the detector finds with the
confidence that starts a track, which is what it settles on in a barn where
nothing moves.

A fisheye puts the whole barn in a picture 2,944 pixels wide, more than twice
what the application analyses. `whole` hands the application that picture as
it would get it, shrunk to its width. `near` hands it nine windows of the
picture at the camera's own sharpness, each as wide as the application
analyses. By the publisher's calibration this lens keeps a cow's shape
wherever she is, so a window shows about what an ordinary camera aimed at that
part of the barn would. Only it is not turned as that camera would be: to one
side of the picture, what lies further from the camera is not above the cow
but beside or below her. `turned` says by how much. Every picture is therefore
shown four times, a quarter turn further each time, so that every cow is seen
once with the barn upright around her, once on its head and twice on its side,
wherever in her barn she happens to be.
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from itertools import product
from pathlib import Path

import cv2
import numpy as np

from app_policy import Rules, fit_crops
from app_run import SOURCE, detector_config, digest
from matching import match, overlap

from aidetector.adapters.inference.identity_observations import infrared
from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.inference.yolo import open_detector
from aidetector.adapters.media.images import shrink_image
from aidetector.configuration import Config
from aidetector.domain.models import Frame
from aidetector.version import TYPE

# A picture's sides, in pixels.
SIDE = 2944
# The publisher's calibration of one of the cameras: a point at an angle off the lens's axis
# lies 2 * FOCAL * tan(angle / 2) pixels from the middle of the picture.
FOCAL = 722
# A window is as wide as the application analyses; three across and three down cover a picture.
WINDOW = 1280
CORNERS = (0, (SIDE - WINDOW) // 2, SIDE - WINDOW)
POSTURES = {2: "standing", 3: "lying"}
# The cameras' serial numbers begin differently in the two barns.
BARNS = {"0002D1A4": "barn with four cameras", "0002D1AA": "barn with twelve cameras"}
# Degrees off straight down, degrees the barn is turned, and a cow's longer side in the
# analysed picture, to count by.
ANGLES = (0, 20, 40, 60, 90)
TURNS = (0, 45, 90, 135, 181)
SIZES = (0, 64, 128, 192, 256, SIDE)


def off_axis(box):
    """How many degrees off the lens's axis the middle of a box lies; the lens looks down."""
    left, top, right, bottom = box
    distance = np.hypot((left + right) / 2 - SIDE / 2, (top + bottom) / 2 - SIDE / 2)
    return float(np.degrees(2 * np.arctan(distance / (2 * FOCAL))))


def turned(box):
    """How many degrees the barn around a cow is turned in the picture.

    An ordinary camera that looks down at an angle draws what lies further away above
    what lies nearer: 0. In a fisheye's picture that holds only straight above the
    middle; straight below it the barn stands on its head: 180.
    """
    left, top, right, bottom = box
    return float(
        np.degrees(np.arctan2(abs((left + right) / 2 - SIDE / 2), SIDE / 2 - (top + bottom) / 2))
    )


def quarter(box, turns):
    """Where a box lies after its picture is turned so many quarter turns anticlockwise."""
    for _ in range(turns):
        left, top, right, bottom = box
        box = [top, SIDE - right, bottom, SIDE - left]
    return box


def pictures(labels, folder):
    """The publisher's pictures that lie in `folder`, with their camera, day and boxed cows."""
    record = json.loads(Path(labels).read_text())
    cows = defaultdict(list)
    for annotation in record["annotations"]:
        left, top, width, height = (value * SIDE for value in annotation["bbox"])
        cows[annotation["image_id"]].append(
            {
                "posture": POSTURES[annotation["category_id"]],
                "box": [left, top, left + width, top + height],
            }
        )
    for image in record["images"]:
        file = Path(folder) / f"{image['id']}_{image['file_name']}"
        if file.exists():
            camera, day = re.search(r"/(0002D1[0-9A-F]{6})/(20\d{6})/", image["coco_url"]).groups()
            yield {"file": file, "camera": camera, "day": day, "cows": cows[image["id"]]}


def windows(view):
    """The parts of a picture handed to the application, as (left, top, side)."""
    if view == "whole":
        return [(0, 0, SIDE)]
    return [(left, top, WINDOW) for top, left in product(CORNERS, CORNERS)]


def window_of(box, parts):
    """The window that holds a box whole and has it nearest its middle, if any does."""
    left, top, right, bottom = box
    holding = [
        (np.hypot((left + right) / 2 - x - side / 2, (top + bottom) / 2 - y - side / 2), place)
        for place, (x, y, side) in enumerate(parts)
        if x <= left and y <= top and right <= x + side and bottom <= y + side
    ]
    return min(holding)[1] if holding else None


def fresh(detector):
    """Make the application's tracker forget what it followed: the next picture is another.

    The trackers are made when the first picture is handed over.
    """
    for tracker in getattr(detector.model.predictor, "trackers", ()):
        tracker.reset()


def found(arguments):
    config = Config.model_validate(
        {"detectors": [detector_config(arguments.preset, arguments.detector_weights)]}
    )
    settings = config.detectors[0]
    rules = Rules(
        0,
        0,
        min_crop_size=settings.identity.min_crop_size,
        max_overlap=settings.identity.max_overlap,
        whole_animal=True,
    )
    parts = windows(arguments.view)
    models = (ModelRequirements(settings.yolo.model, settings.yolo.imgsz, 1),)
    cows, seen, in_no_window = [], 0, 0
    with (
        inference_runtime(config.onnx, models, TYPE) as options,
        open_detector(settings.yolo, config.onnx, (SOURCE,), TYPE, options) as detector,
    ):
        for picture, turns in product(pictures(arguments.labels, arguments.pictures), range(4)):
            image = np.ascontiguousarray(np.rot90(cv2.imread(str(picture["file"])), turns))
            taken = datetime.strptime(picture["day"], "%Y%m%d")
            placed = defaultdict(list)
            for cow in picture["cows"]:
                cow = {**cow, "box": quarter(cow["box"], turns)}
                placed[window_of(cow["box"], parts)].append(cow)
            if turns == 0:
                seen += 1
                in_no_window += len(placed[None])
            for place, (x, y, side) in enumerate(parts):
                if not placed[place]:
                    continue
                analysed = shrink_image(
                    image[y : y + side, x : x + side], settings.detection.frames_width
                )
                scale = side / analysed.shape[1]
                dark = infrared(analysed)
                fresh(detector)
                observation = detector.detect({SOURCE: (Frame(taken, analysed),)})[SOURCE][-1]
                boxes = [[box.x1, box.y1, box.x2, box.y2] for box in observation.boxes]
                fit = fit_crops(
                    [
                        {"index": 0, "box": box, "frame_size": analysed.shape[1::-1]}
                        for box in boxes
                    ],
                    rules,
                )
                asked = [
                    [(value - offset) / scale for value, offset in zip(cow["box"], (x, y, x, y))]
                    for cow in placed[place]
                ]
                partner = dict(match(asked, boxes))
                shared = overlap(asked, boxes)
                for at, cow in enumerate(placed[place]):
                    box = asked[at]
                    cows.append(
                        {
                            "picture": picture["file"].name,
                            "camera": picture["camera"],
                            "day": picture["day"],
                            "quarter_turns": turns,
                            "infrared": dark,
                            "posture": cow["posture"],
                            "off_axis": off_axis(cow["box"]),
                            "turned": turned(cow["box"]),
                            "longer_side": max(box[2] - box[0], box[3] - box[1]),
                            "found": at in partner,
                            "fit": at in partner and fit[partner[at]],
                            "overlap": float(shared[at].max()) if boxes else 0.0,
                        }
                    )
            if turns == 3 and seen % 50 == 0:
                print(seen, "pictures,", len(cows), "cows in four turns", flush=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(
            {
                "view": arguments.view,
                "preset": json.loads(arguments.preset.read_text()),
                "detector_weights_sha256": digest(arguments.detector_weights),
                "pictures": seen,
                "cows_in_no_window": in_no_window,
                "cows": cows,
            }
        )
        + "\n"
    )
    print(seen, "pictures,", len(cows), "cows in four turns")


def counted(cows):
    """How many cows, and the shares that were found and whose box was fit to be evidence."""
    if not cows:
        return {"cows": 0}
    return {
        "cows": len(cows),
        "found": sum(cow["found"] for cow in cows) / len(cows),
        "fit": sum(cow["fit"] for cow in cows) / len(cows),
    }


def between(cows, key, limits):
    """Cows counted by the range their `key` falls in."""
    return {
        f"{low}-{high}": counted([cow for cow in cows if low <= cow[key] < high])
        for low, high in zip(limits, limits[1:])
    }


def summarised(cows):
    """Cows counted by posture and by what may make a cow hard to find."""
    postures = {}
    for posture in POSTURES.values():
        own = [cow for cow in cows if cow["posture"] == posture]
        postures[posture] = {
            **counted(own),
            "by_degrees_off_straight_down": between(own, "off_axis", ANGLES),
            "by_degrees_off_straight_down_and_turned": {
                f"{low}-{high}": between(
                    [cow for cow in own if low <= cow["off_axis"] < high], "turned", TURNS
                )
                for low, high in zip(ANGLES[2:], ANGLES[3:])
            },
            "by_longer_side_in_the_analysed_picture": between(own, "longer_side", SIZES),
            "by_light": {
                "daylight or lamps": counted([cow for cow in own if not cow["infrared"]]),
                "infrared": counted([cow for cow in own if cow["infrared"]]),
            },
            "by_barn": {
                barn: counted([cow for cow in own if cow["camera"].startswith(serial)])
                for serial, barn in BARNS.items()
            },
        }
    return {
        **counted(cows),
        "median_overlap_of_the_found": float(
            np.median([cow["overlap"] for cow in cows if cow["found"]])
        ),
        **postures,
    }


def shown(name, part, depth):
    """A counted group on one line, and below it the groups it is divided into."""
    line = "  " * depth + name.replace("_", " ")
    if part.get("cows"):
        line += f": {part['cows']} cows, found {part['found']:.1%}, fit {part['fit']:.1%}"
    if part.get("cows") != 0:
        print(line)
    for key, value in part.items():
        if isinstance(value, dict):
            shown(key, value, depth + 1)


def summary(arguments):
    views = {}
    for file in arguments.found:
        record = json.loads(file.read_text())
        cows = record["cows"]
        views[record["view"]] = {
            "yolo": record["preset"]["yolo"],
            "detector_weights_sha256": record["detector_weights_sha256"],
            "pictures": record["pictures"],
            "cameras": len({cow["camera"] for cow in cows}),
            "days": len({cow["day"] for cow in cows}),
            "cows_in_no_window": record["cows_in_no_window"],
            "as_filmed": summarised([cow for cow in cows if cow["quarter_turns"] == 0]),
            "in_all_four_turns": summarised(cows),
        }
    arguments.output.write_text(json.dumps({"views": views}, indent=2) + "\n")
    for view, result in views.items():
        print(f"{view}: {result['pictures']} pictures")
        for turns in ("as_filmed", "in_all_four_turns"):
            shown(turns, result[turns], 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("found", help="Which boxed cows the application finds")
    command.add_argument("labels", type=Path, help="The publisher's normalized_annotations file")
    command.add_argument("pictures", type=Path, help="Folder of the publisher's raw pictures")
    command.add_argument("--view", choices=("whole", "near"), required=True)
    command.add_argument("--preset", type=Path, required=True)
    command.add_argument("--detector-weights", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("summary", help="The found cows of each view, counted")
    command.add_argument("found", type=Path, nargs="+", help="Written by found")
    command.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    {"found": found, "summary": summary}[arguments.command](arguments)


if __name__ == "__main__":
    main()
