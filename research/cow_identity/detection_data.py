"""Add publisher-split adult torso annotations to the fixed calf detector data."""

import argparse
import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from benchmark import write_json


def enclosing_box(box, width, height):
    x, y, w, h, radians = box
    cx, cy = x + w / 2, y + h / 2
    extent_x = abs(w * math.cos(radians)) + abs(h * math.sin(radians))
    extent_y = abs(w * math.sin(radians)) + abs(h * math.cos(radians))
    return (
        max(0, cx - extent_x / 2),
        max(0, cy - extent_y / 2),
        min(width, cx + extent_x / 2),
        min(height, cy + extent_y / 2),
    )


def add_adults(archive, output, split, count):
    annotation_path = next(
        name
        for name in archive.namelist()
        if name.endswith(f"Train/annotations/instances_{split}.json")
    )
    raw = archive.read(annotation_path)
    document = json.loads(raw)
    by_image = defaultdict(list)
    for annotation in document["annotations"]:
        by_image[annotation["image_id"]].append(annotation["bbox"])
    images = sorted(document["images"], key=lambda row: row["id"])
    selected = [
        images[index] for index in np.linspace(0, len(images) - 1, count, dtype=int)
    ]
    prefix = annotation_path.split("/annotations/")[0]
    manifest = []
    for row in selected:
        image = archive.read(f"{prefix}/images/{split}/{row['file_name']}")
        name = f"cows2021_{row['id']:05d}"
        (output / "images" / split / f"{name}.jpg").write_bytes(image)
        width, height = row["width"], row["height"]
        labels = []
        for box in by_image[row["id"]]:
            x1, y1, x2, y2 = enclosing_box(box, width, height)
            if x2 <= x1 or y2 <= y1:
                raise ValueError("Adult annotation has no visible extent")
            labels.append(
                f"0 {(x1 + x2) / (2 * width)} {(y1 + y2) / (2 * height)} "
                f"{(x2 - x1) / width} {(y2 - y1) / height}"
            )
        (output / "labels" / split / f"{name}.txt").write_text("\n".join(labels) + "\n")
        manifest.append(
            {
                "image_id": row["id"],
                "source": row["file_name"],
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "boxes": len(labels),
            }
        )
    return {
        "annotation_file": annotation_path,
        "annotation_sha256": hashlib.sha256(raw).hexdigest(),
        "images": manifest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("calves", "adults", "protocol", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh output directory")
    protocol = json.loads(args.protocol.read_text())
    previous = json.loads((args.calves / "protocol.json").read_text())
    if any(
        previous[key] != protocol[key]
        for key in ("video_sha256", "source_annotations_sha256", "splits")
    ):
        parser.error("Calf source and splits must remain unchanged")
    for kind, suffix in (("images", ".jpg"), ("labels", ".txt")):
        for split in ("train", "val"):
            destination = args.output / kind / split
            destination.mkdir(parents=True)
            for source in (args.calves / kind / split).glob(f"*{suffix}"):
                shutil.copyfile(source, destination / source.name)
    with ZipFile(args.adults) as archive:
        manifest = {
            split: add_adults(archive, args.output, split, count)
            for split, count in protocol["adult_data"]["sample_counts"].items()
        }
    (args.output / "data.yaml").write_text(
        f"path: {args.output.resolve()}\ntrain: images/train\nval: images/val\nnames: [cow]\n"
    )
    write_json(args.output / "adult-manifest.json", manifest)
    write_json(args.output / "protocol.json", protocol)
    print(
        json.dumps(
            {
                name: {
                    "images": len(value["images"]),
                    "boxes": sum(row["boxes"] for row in value["images"]),
                }
                for name, value in manifest.items()
            }
        )
    )


if __name__ == "__main__":
    main()
