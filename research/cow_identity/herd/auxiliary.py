"""Assemble photographs of other farms' cows from public identity datasets.

They are never enrolled or evaluated. Their only use is to keep a herd model
aware that many other cows exist, so that it does not treat every animal as one
of the few it was taught.
"""

import argparse
import csv
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


def spread(items, count):
    """`count` items evenly spaced through a sorted list."""
    items = sorted(items)
    if len(items) <= count:
        return items
    return [items[round(step)] for step in np.linspace(0, len(items) - 1, count)]


def write(data, target, limit=448):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return image is not None and write_image(image, target, limit)


def write_image(image, target, limit=448):
    height, width = image.shape[:2]
    scale = limit / max(height, width)
    if scale < 1:
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return True


def from_zip(archive, pattern, group, per_group, source, output):
    """Members matching `pattern`, grouped by `group(match)` into (identity, stratum)."""
    rows = []
    with zipfile.ZipFile(archive) as bundle:
        members = defaultdict(list)
        for name in bundle.namelist():
            match = re.search(pattern, name)
            if match:
                members[group(match)].append(name)
        for (identity, stratum), names in sorted(members.items()):
            for name in spread(names, per_group):
                target = output / source / str(identity) / f"{stratum}-{Path(name).stem}.jpg"
                if target.exists() or write(bundle.read(name), target):
                    rows.append(
                        {
                            "path": str(target.relative_to(output)),
                            "source": source,
                            "identity": f"{source}:{identity}",
                        }
                    )
    return rows


def from_folders(root, per_identity, source, output):
    """`root/<day>/<identity>/<file>`: spread each identity over days and cameras."""
    members = defaultdict(list)
    for path in Path(root).glob("*/*/*.jpg"):
        members[path.parent.name].append(path)
    rows = []
    for identity, paths in sorted(members.items()):
        for path in spread(paths, per_identity):
            target = output / source / identity / f"{path.parent.parent.name}-{path.name}"
            if target.exists() or write(path.read_bytes(), target):
                rows.append(
                    {
                        "path": str(target.relative_to(output)),
                        "source": source,
                        "identity": f"{source}:{identity}",
                    }
                )
    return rows


def from_masks(root, subset, per_identity, source, output):
    """SideViewCows2026: frames listed in `manifest.csv`, each cut to the box around its mask.

    Only the files that are on disk are used; the dataset is large and need not be complete.
    """
    members = defaultdict(list)
    with (Path(root) / "manifest.csv").open() as stream:
        for row in csv.DictReader(stream):
            image, mask = Path(root) / row["image_path"], Path(root) / row["mask_path"]
            if row["subset"] == subset and image.exists() and mask.exists():
                members[row["individual_id"]].append((image, mask))
    rows = []
    for identity, pairs in sorted(members.items()):
        for image, mask in spread(pairs, per_identity):
            target = output / source / identity / f"{image.stem}.jpg"
            if not target.exists():
                ys, xs = np.nonzero(cv2.imread(str(mask), cv2.IMREAD_GRAYSCALE))
                picture = cv2.imread(str(image))[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
                write_image(picture, target)
            rows.append(
                {
                    "path": str(target.relative_to(output)),
                    "source": source,
                    "identity": f"{source}:{identity}",
                }
            )
    return rows


SOURCES = {
    # MmCows, CC BY-NC-SA 4.0: one pen of sixteen cows, lying and standing.
    "mmcows": lambda data, output: from_zip(
        data / "mmcows" / "cropped_bboxes.zip",
        r"cropped_bboxes/(standing|lying)/(\d+)/[^/]+\.jpg$",
        lambda match: (int(match[2]), match[1]),
        400,
        "mmcows",
        output,
    ),
    # MultiCamCows2024, Non-Commercial Government Licence: three cameras, seven days.
    "multicam": lambda data, output: from_folders(
        data
        / "MultiCamCows2024"
        / "extracted"
        / "2inu67jru7a6821kkgehxg3cv2"
        / "MultiCamCows2024Root",
        80,
        "multicam",
        output,
    ),
    # Cows2021, Non-Commercial Government Licence: seen from above.
    "cows2021": lambda data, output: from_zip(
        data / "Cows2021" / "Cows2021.zip",
        r"Identification/Test/(\d+)/[^/]+\.jpg$",
        lambda match: (int(match[1]), "top"),
        40,
        "cows2021",
        output,
    ),
    # SideViewCows2026, CC BY 4.0: the right side, at a parlour entrance.
    "sideview": lambda data, output: from_masks(
        data / "SideViewCows2026", "parlor", 240, "sideview", output
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=SOURCES,
        default=["mmcows", "multicam", "cows2021"],
        help="A herd evaluated on one of these farms must start from weights taught without it",
    )
    arguments = parser.parse_args()
    rows = []
    for source in arguments.sources:
        rows += SOURCES[source](arguments.datasets, arguments.output)
    report(rows, arguments.output)


def report(rows, output):
    (output / "auxiliary.json").write_text(json.dumps(rows) + "\n")
    counts = defaultdict(set)
    for row in rows:
        counts[row["source"]].add(row["identity"])
    print(len(rows), {source: len(ids) for source, ids in counts.items()})


if __name__ == "__main__":
    main()
