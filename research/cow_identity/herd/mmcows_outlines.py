"""Crops of the MmCows pen as the application would cut them, plain and by the cow's outline.

Where cows stand half behind each other, a box holds parts of two animals.
The stock detector also draws every cow's outline. Here it finds the cows in
the labelled pictures of some hours, at the width the application analyses;
a found cow takes the publisher's number of the box it overlaps by half or
more, as a farmer would confirm her. Every such cow is cut out twice: by her
box, and with everything outside her outline blacked out. `mmcows_boxes.py`
then tells how well either kind of crop is told apart.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

import mmcows
from mounting_boxes import overlap
from mounting_live import COW

from aidetector.adapters.media.images import shrink_image

# What the Cow Identity preset asks of the detector and of a crop.
INPUT, CONFIDENCE, MIN_SIDE = 1280, 0.1, 32


def numbered(found, truth):
    """Each found box with the publisher's cow it overlaps most, one to one, by half or more."""
    pairs = sorted(
        (
            (overlap(box, cow[1:]), position, number)
            for position, box in enumerate(found)
            for number, cow in enumerate(truth)
        ),
        reverse=True,
    )
    taken, named = set(), {}
    for score, position, number in pairs:
        if score >= 0.5 and position not in named and number not in taken:
            named[position] = truth[number][0]
            taken.add(number)
    return named


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Gets a plain and a masked folder")
    parser.add_argument("--between", nargs=2, default=mmcows.PHOTOGRAPHS, metavar="HH:MM")
    parser.add_argument("--every", type=int, default=8, help="Of the labelled pictures")
    parser.add_argument("--detector-weights", type=Path, required=True)
    arguments = parser.parse_args()
    first, last = map(mmcows.seconds_at, arguments.between)
    model = YOLO(str(arguments.detector_weights))
    bundle, _ = mmcows.archive(mmcows.LABELLED)
    rows = {"plain": [], "masked": []}
    annotated = 0
    for camera in mmcows.CAMERAS:
        wanted = [
            member
            for member in mmcows.labelled_members(bundle, camera)
            if first <= mmcows.stamp(member) < last
        ]
        for member in wanted[:: arguments.every]:
            at = mmcows.barn_time(mmcows.stamp(member))
            label = member.replace("/images/", "/labels/combined/").replace(".jpg", ".txt")
            picture = cv2.imdecode(np.frombuffer(bundle.read(member), np.uint8), cv2.IMREAD_COLOR)
            image = shrink_image(picture, INPUT)
            height, width = image.shape[:2]
            truth = [
                (
                    cow,
                    (x - w / 2) * width,
                    (y - h / 2) * height,
                    (x + w / 2) * width,
                    (y + h / 2) * height,
                )
                for cow, x, y, w, h in mmcows.boxes(bundle.read(label).decode())
            ]
            annotated += len(truth)
            result = model.predict(
                image, imgsz=INPUT, conf=CONFIDENCE, classes=[COW], retina_masks=True, verbose=False
            )[0]
            if result.masks is None:
                continue
            found = result.boxes.xyxy.round().int().tolist()
            outlines = result.masks.data.cpu().numpy() > 0.5
            for position, cow in numbered(found, truth).items():
                x1, y1, x2, y2 = found[position]
                if min(x2 - x1, y2 - y1) < MIN_SIDE:
                    continue
                plain = image[y1:y2, x1:x2]
                masked = plain.copy()
                masked[~outlines[position][y1:y2, x1:x2]] = 0
                path = Path("photographs") / f"cow_{cow}" / f"{camera}-{mmcows.stamp(member)}.jpg"
                for kind, crop in (("plain", plain), ("masked", masked)):
                    target = arguments.output / kind / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(target), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    rows[kind].append(
                        {
                            "path": str(path),
                            "cow": cow,
                            "camera": str(camera),
                            "date": at.strftime("%Y%m%d"),
                            "time": at.strftime("%H%M%S"),
                            "clip": f"{camera}-{at:%Y%m%d-%H%M%S}",
                        }
                    )
    for kind, found in rows.items():
        (arguments.output / kind / "classification.json").write_text(json.dumps(found) + "\n")
    print(f"{len(rows['plain'])} of {annotated} annotated cows found and cut")


if __name__ == "__main__":
    main()
