"""Assemble photographs of other farms' cows from public identity datasets.

They are never enrolled or evaluated. Their only use is to keep a herd model
aware that many other cows exist, so that it does not treat every animal as one
of the few it was taught.
"""

import argparse
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
    if image is None:
        return False
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    data, output = arguments.datasets, arguments.output
    rows = from_zip(
        data / "mmcows" / "cropped_bboxes.zip",
        r"cropped_bboxes/(standing|lying)/(\d+)/[^/]+\.jpg$",
        lambda match: (int(match[2]), match[1]),
        400,
        "mmcows",
        output,
    )
    rows += from_folders(
        data
        / "MultiCamCows2024"
        / "extracted"
        / "2inu67jru7a6821kkgehxg3cv2"
        / "MultiCamCows2024Root",
        80,
        "multicam",
        output,
    )
    rows += from_zip(
        data / "Cows2021" / "Cows2021.zip",
        r"Identification/Test/(\d+)/[^/]+\.jpg$",
        lambda match: (int(match[1]), "top"),
        40,
        "cows2021",
        output,
    )
    (output / "auxiliary.json").write_text(json.dumps(rows) + "\n")
    counts = defaultdict(set)
    for row in rows:
        counts[row["source"]].add(row["identity"])
    print(len(rows), {source: len(ids) for source, ids in counts.items()})


if __name__ == "__main__":
    main()
