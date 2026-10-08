"""Cut the publisher's own boxes out of sampled frames.

These crops isolate identification from localization and tracking: every
annotated animal gets a crop, whether or not the detector found it.
"""

import argparse
import json
from pathlib import Path

import cv2

from ethz import frame_labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    index = json.loads((arguments.frames / "frames.json").read_text())
    arguments.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for frame in index["frames"]:
        image = cv2.imread(str(arguments.frames / frame["file"]))
        height, width = image.shape[:2]
        truth = frame_labels(arguments.labels, index["video"], frame["index"], width, height)
        for position, (cow, left, top, right, bottom) in enumerate(truth):
            left, top = max(0, int(left)), max(0, int(top))
            right, bottom = min(width, int(right + 0.5)), min(height, int(bottom + 0.5))
            if right - left < 8 or bottom - top < 8:
                continue
            name = f"{frame['index']:06d}-{position:02d}.jpg"
            cv2.imwrite(
                str(arguments.output / name),
                image[top:bottom, left:right],
                [cv2.IMWRITE_JPEG_QUALITY, 92],
            )
            rows.append(
                {
                    "path": name,
                    "index": frame["index"],
                    "seconds": frame["seconds"],
                    "box": [left, top, right, bottom],
                    "cow": cow,
                    # The publisher's identity is the track here: an oracle tracker.
                    "track": cow,
                    "confidence": 1.0,
                    "frame_size": [width, height],
                }
            )
    (arguments.output / "crops.json").write_text(json.dumps(rows) + "\n")
    print(arguments.output, len(rows), "crops")


if __name__ == "__main__":
    main()
