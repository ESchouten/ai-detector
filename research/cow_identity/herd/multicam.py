"""A third farm: MultiCamCows2024, ninety cows under three ceiling cameras.

MultiCamCows2024 (https://data.bris.ac.uk/data/dataset/2inu67jru7a6821kkgehxg3cv2,
Non-Commercial Government Licence) films the passage from a milking parlour
with three cameras in the ceiling, on seven days of August 2023. The publisher
cut every cow's back out of five pictures a second, turned so that she walks
to the right, checked every walk by hand and numbered the cows. A folder holds
one cow's pictures of one day, each named by its place in her walk and by the
camera.

Nothing of the herd method was developed on this farm. The frozen starting
weights were taught its cows, so a herd of this farm starts from weights that
were taught without it.
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

import requests

SOURCE = "https://data.bris.ac.uk/datasets/2inu67jru7a6821kkgehxg3cv2/MultiCamCows2024Root/"
CAMERAS = (1, 2, 3)
DAYS = (
    "2023Aug14",
    "2023Aug15",
    "2023Aug16",
    "2023Aug17",
    "2023Aug18",
    "2023Aug19",
    "2023Aug20",
)
# Photographs are confirmed on the first three days and validated on the two after.
# The last two days are the test: they stay unseen until a version passes validation.
PHOTOGRAPHS, VALIDATION, TEST = DAYS[:3], DAYS[3:5], DAYS[5:]
COWS = tuple(range(1, 91))
# Every fourth cow by the publisher's number is an unknown animal.
WITHHELD = COWS[3::4]
# Pictures the publisher kept of each second.
RATE = 5


def walks(root, days, cows):
    """Each cow's walk under each camera on each day, with her pictures in order."""
    for day in days:
        for cow in cows:
            pictures = defaultdict(list)
            for file in sorted((Path(root) / day / f"{cow:03d}").glob("*.jpg")):
                pictures[int(file.stem.split("_")[1])].append(file)
            for camera, files in sorted(pictures.items()):
                yield {"day": day, "cow": cow, "camera": camera, "files": files}


def listed(page):
    """The clips a folder page of the publisher's server names, with their sizes in bytes."""
    return [
        (name, int(size))
        for name, size in re.findall(
            r'<a href="([^"]+\.mp4)">[^<]+</a></td>\s*<td>[^<]*</td>\s*<td>(\d+)</td>', page
        )
    ]


def fetch(arguments):
    """The cameras' footage of the chosen days; a clip that was cut short is carried on."""
    for day in arguments.days:
        for camera in CAMERAS:
            folder = f"{SOURCE}videos/camera{camera}/{day}/"
            page = requests.get(folder, timeout=60)
            page.raise_for_status()
            for name, size in listed(page.text):
                target = arguments.output / f"camera{camera}" / day / name
                target.parent.mkdir(parents=True, exist_ok=True)
                held = target.stat().st_size if target.exists() else 0
                if held == size:
                    continue
                with requests.get(
                    folder + name, headers={"Range": f"bytes={held}-"}, stream=True, timeout=60
                ) as response:
                    response.raise_for_status()
                    with target.open("ab") as file:
                        for block in response.iter_content(1 << 20):
                            file.write(block)
                print(day, camera, name, size, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("fetch", help=fetch.__doc__)
    command.add_argument("output", type=Path)
    command.add_argument("--days", nargs="+", choices=DAYS, required=True)
    command.set_defaults(run=fetch)
    arguments = parser.parse_args()
    arguments.run(arguments)


if __name__ == "__main__":
    main()
