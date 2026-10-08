"""Cut every detected box out of its sampled frame, once.

The crop is the detector's rectangle, as the application would hand it to an
identity encoder. Publisher labels are not read here.
"""

import argparse
import json
from pathlib import Path

import cv2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detections", type=Path)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    detections = json.loads(arguments.detections.read_text())
    files = {
        frame["index"]: frame["file"]
        for frame in json.loads((arguments.frames / "frames.json").read_text())["frames"]
    }
    arguments.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for frame in detections["frames"]:
        image = cv2.imread(str(arguments.frames / files[frame["index"]]))
        height, width = image.shape[:2]
        for position, box in enumerate(frame["boxes"]):
            left, top, right, bottom = box["box"]
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
                    "box": box["box"],
                    "confidence": box["confidence"],
                    "track": box["track"],
                    "frame_size": [width, height],
                }
            )
    (arguments.output / "crops.json").write_text(json.dumps(rows) + "\n")
    print(arguments.output, len(rows), "crops")


if __name__ == "__main__":
    main()
