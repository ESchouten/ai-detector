"""Prepare the public ETH Zurich barn dataset for the herd study.

`photographs` indexes the publisher's identified crops and stores them as the
photographs a farmer would confirm: no larger than the application's camera
picture shows a cow. `frames` stores one frame per second of a tracking video.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from ethz import VIDEOS, classification_rows, sample_frames


def store_photographs(root, output, side):
    rows = classification_rows(root)

    def store(row):
        image = cv2.imread(str(Path(root) / row["path"]))
        scale = side / max(image.shape[:2])
        if scale < 1:
            image = cv2.resize(
                image,
                (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
        target = (Path(output) / row["path"]).with_suffix(".jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return {**row, "path": str(Path(row["path"]).with_suffix(".jpg"))}

    with ThreadPoolExecutor(8) as pool:
        stored = list(pool.map(store, rows))
    (Path(output) / "classification.json").write_text(json.dumps(stored) + "\n")
    return stored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    photographs = commands.add_parser("photographs")
    photographs.add_argument("root", type=Path, help="Folder that contains classification/")
    photographs.add_argument("output", type=Path)
    photographs.add_argument("--side", type=int, default=448, help="Longest side in pixels")
    frames = commands.add_parser("frames")
    frames.add_argument("root", type=Path, help="Folder that contains the video folders")
    frames.add_argument("video", choices=sorted(VIDEOS))
    frames.add_argument("output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "photographs":
        stored = store_photographs(arguments.root, arguments.output, arguments.side)
        print(len(stored), "photographs")
    else:
        sampled = sample_frames(arguments.root, arguments.video, 1.0, arguments.output)
        print(len(sampled), "frames")


if __name__ == "__main__":
    main()
