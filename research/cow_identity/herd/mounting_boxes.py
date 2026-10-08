"""How many cows lie inside the mounting model's box, on mounting pictures of other barns.

An event of another rule takes the names of the cows whose boxes lay mostly
inside its own. Wherever the mounting model finds a mount in a folder of
pictures, the stock detector's cow boxes are held against the mounting box as
the application holds them: by the share of the cow's box that lies inside.
No cow is known in these pictures; this measures the boxes alone.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

import cv2
from ultralytics import YOLO

from mounting_live import COW, share_inside

from aidetector.adapters.media.images import shrink_image

# What the Cow Catcher preset asks of a mount, and the Cow Identity preset of a cow's box.
CONFIDENCE, MIN_SIDE = 0.88, 32


def overlap(box, other):
    """Intersection over union."""
    width = min(box[2], other[2]) - max(box[0], other[0])
    height = min(box[3], other[3]) - max(box[1], other[1])
    shared = max(0, width) * max(0, height)

    def area(corners):
        return (corners[2] - corners[0]) * (corners[3] - corners[1])

    return shared / (area(box) + area(other) - shared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pictures", type=Path, help="Folder of JPEG pictures")
    parser.add_argument("--first", type=int, help="Only this many, in order of name")
    parser.add_argument("--mounting-weights", type=Path, required=True)
    parser.add_argument("--detector-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    mounting = YOLO(str(arguments.mounting_weights))
    animals = YOLO(str(arguments.detector_weights))
    files = sorted(arguments.pictures.glob("*.jpg"))[: arguments.first]
    inside, matching, second = Counter(), [], []
    for file in files:
        image = cv2.imread(str(file))
        # A picture this small shows one animal cut out, not a scene.
        if image is None or min(image.shape[:2]) < 300:
            continue
        image = shrink_image(image, 1280)
        mounts = mounting.predict(image, conf=CONFIDENCE, verbose=False)[0].boxes
        if not len(mounts):
            continue
        mount = mounts.xyxy[int(mounts.conf.argmax())].tolist()
        cows = [
            box
            for box in animals.predict(image, imgsz=1280, conf=0.1, classes=[COW], verbose=False)[0]
            .boxes.xyxy.round()
            .tolist()
            if min(box[2] - box[0], box[3] - box[1]) >= MIN_SIDE
        ]
        shares = sorted((share_inside(box, mount) for box in cows), reverse=True)
        inside[min(3, sum(share > 0.5 for share in shares))] += 1
        matching.append(max((overlap(box, mount) for box in cows), default=0.0))
        second.append(shares[1] if len(shares) > 1 else 0.0)
    result = {
        "pictures": len(files),
        "pictures_with_a_mount": len(matching),
        "a_cow_box_overlaps_the_mounting_box_by_half": sum(value >= 0.5 for value in matching),
        "median_overlap_of_the_best_matching_cow_box": round(median(matching), 3),
        "cows_more_than_half_inside_the_mounting_box": {
            "none": inside[0],
            "one": inside[1],
            "two": inside[2],
            "three_or_more": inside[3],
        },
        "median_share_inside_of_the_second_cow": round(median(second), 3),
    }
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
