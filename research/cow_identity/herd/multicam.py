"""A third farm: MultiCamCows2024, ninety cows under three ceiling cameras.

MultiCamCows2024 (https://data.bris.ac.uk/data/dataset/2inu67jru7a6821kkgehxg3cv2,
Non-Commercial Government Licence) films the passage from a milking parlour
with three cameras in the ceiling, on seven days of August 2023. The publisher
cut every cow's back out of five pictures a second, turned so that she walks
to the right, checked every walk by hand and numbered the cows. A folder holds
one cow's pictures of one day, each named by its place in her walk and by the
camera. `multicam_locate` and `multicam_fill` find those pictures again in the
cameras' footage.

Nothing of the herd method was developed on this farm. The frozen starting
weights were taught its cows, so a herd of this farm starts from weights that
were taught without it. Its sessions, one camera's footage of one day,
register with the ETH index so that the same scripts run them: `run`, `track`
and `score` hand over to `app_run`, `app_track` and `app_score`.
"""

import argparse
import importlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import requests

import ethz

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
# Pictures the publisher kept of each second, of the cameras' 25.
RATE = 5
FILMED = 25
# The cameras' frame, in points.
WIDTH, HEIGHT = 2560, 1440
# A cow walks by once a day, so no photograph of an earlier day is a near copy of a session.
# Sessions begin after half past twelve; the application is told that they begin then.
SESSIONS = {f"multicam-{day[-2:]}-cam{camera}": (day, camera) for day in DAYS for camera in CAMERAS}
VIDEOS = {
    name: {
        "start": f"2023-08-{day[-2:]}T12:30:00",
        "minutes": 120,
        "camera": str(camera),
        "gap_hours": 12,
    }
    for name, (day, camera) in SESSIONS.items()
}
ethz.VIDEOS.update(VIDEOS)
# A picture ends at the cow's shoulders; her neck and head reach about this share of its length
# further, in the direction she walks.
HEAD = 0.35


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


def clips(footage, day, camera):
    """One session's clips in the order they were filmed; each is named by when it begins."""
    return sorted((Path(footage) / f"camera{camera}" / day).glob("*.mp4"))


def kept_frames(clip):
    """The frames of a clip that the publisher cut pictures from: every fifth, with its number."""
    capture = cv2.VideoCapture(str(clip))
    number = 0
    while capture.grab():
        if number % (FILMED // RATE) == 0:
            yield number, capture.retrieve()[1]
        number += 1


def upright(corners, width, height):
    """The upright box around a cow whose picture lies at `corners`, neck and head taken in.

    The corners are the picture's own, clockwise from its top left, and the cow in it walks
    to the right: her head lies beyond the second and third.
    """
    quad = np.array(corners)
    ahead = (quad[1] - quad[0]) * HEAD
    points = np.concatenate([quad, quad[1:3] + ahead])
    left, top = np.clip(points.min(0), 0, (width, height))
    right, bottom = np.clip(points.max(0), 0, (width, height))
    return float(left), float(top), float(right), float(bottom)


def found_in(record):
    """A located session's pictures by clip and frame, one of each cow in a frame."""
    cows = defaultdict(dict)
    for picture in sorted(record["located"], key=lambda picture: -picture["difference"]):
        cows[picture["clip"], picture["frame"]][picture["cow"]] = picture
    return cows


def frames(arguments):
    """One session as the application is handed it: five pictures a second, shrunk to its width."""
    day, camera = SESSIONS[arguments.video]
    arguments.output.mkdir(parents=True, exist_ok=True)
    index = []
    for clip in clips(arguments.footage, day, camera):
        for _, image in kept_frames(clip):
            at = len(index)
            cv2.imwrite(
                str(arguments.output / f"{at:06d}.jpg"),
                cv2.resize(
                    image,
                    (arguments.width, round(HEIGHT * arguments.width / WIDTH)),
                    interpolation=cv2.INTER_AREA,
                ),
                [cv2.IMWRITE_JPEG_QUALITY, 92],
            )
            index.append({"index": at, "seconds": at / RATE, "file": f"{at:06d}.jpg"})
    (arguments.output / "frames.json").write_text(
        json.dumps({"video": arguments.video, "rate": float(RATE), "frames": index}) + "\n"
    )
    print(arguments.video, len(index), "pictures")


def labels(arguments):
    """The publisher's cows in each picture of a session.

    A picture's label holds the upright box of every cow the publisher cut out of that
    frame; most pictures show none and have an empty label.
    """
    record = json.loads(arguments.located.read_text())
    index = json.loads((arguments.frames / "frames.json").read_text())
    folder = arguments.labels / index["video"] / "labels"
    folder.mkdir(parents=True, exist_ok=True)
    first, read = {}, 0
    for clip, count in record["frames_read"].items():
        first[clip] = read
        read += count
    lines = defaultdict(list)
    for (clip, number), cows in found_in(record).items():
        for cow, picture in sorted(cows.items()):
            left, top, right, bottom = upright(picture["corners"], WIDTH, HEIGHT)
            lines[first[clip] + number * RATE // FILMED].append(
                f"{cow} {(left + right) / 2 / WIDTH:.6f} {(top + bottom) / 2 / HEIGHT:.6f} "
                f"{(right - left) / WIDTH:.6f} {(bottom - top) / HEIGHT:.6f}\n"
            )
    for frame in index["frames"]:
        (folder / f"frame_{frame['index']:06d}.txt").write_text(
            "".join(lines.get(frame["index"], ()))
        )
    print(index["video"], len(lines), "of", len(index["frames"]), "pictures show a cut-out cow")


def photographs(arguments):
    """The photographs a farmer confirms: pictures of every walk, boxed in their frames.

    A walk's located pictures are spread over it, and each is cut out of its frame by the
    upright box around the cow, as large as the application's picture shows her.
    """
    rows = []
    for file in arguments.located:
        record = json.loads(file.read_text())
        day, camera = record["day"], record["camera"]
        walk = defaultdict(list)
        for picture in record["located"]:
            walk[picture["cow"]].append(picture)
        chosen = defaultdict(list)
        for pictures in walk.values():
            count = min(arguments.per_walk, len(pictures))
            for position in np.linspace(0, len(pictures) - 1, count).round().astype(int):
                chosen[pictures[position]["clip"]].append(pictures[position])
        for clip in clips(arguments.footage, day, camera):
            capture = cv2.VideoCapture(str(clip))
            begun = datetime.strptime(clip.stem, "%Y-%m-%dT%H-%M-%S")
            for picture in sorted(chosen[clip.name], key=lambda picture: picture["frame"]):
                capture.set(cv2.CAP_PROP_POS_FRAMES, picture["frame"])
                image = capture.read()[1]
                height, width = image.shape[:2]
                left, top, right, bottom = map(round, upright(picture["corners"], width, height))
                cut = image[top:bottom, left:right]
                scale = arguments.width / width
                size = (max(1, round(cut.shape[1] * scale)), max(1, round(cut.shape[0] * scale)))
                at = begun + timedelta(seconds=picture["frame"] / FILMED)
                path = (
                    Path("photographs")
                    / f"cow_{picture['cow']}"
                    / f"{day}-cam{camera}-{clip.stem}-{picture['frame']}.jpg"
                )
                (arguments.output / path).parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(
                    str(arguments.output / path),
                    cv2.resize(cut, size, interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 95],
                )
                rows.append(
                    {
                        "path": str(path),
                        "cow": picture["cow"],
                        "camera": str(camera),
                        "date": at.strftime("%Y%m%d"),
                        "time": at.strftime("%H%M%S"),
                        "clip": f"{day}-cam{camera}-cow{picture['cow']}",
                    }
                )
    (arguments.output / "classification.json").write_text(json.dumps(rows) + "\n")
    print(len(rows), "photographs of", len({row["cow"] for row in rows}), "cows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("fetch", help="The cameras' footage of some days")
    command.add_argument("output", type=Path)
    command.add_argument("--days", nargs="+", choices=DAYS, required=True)
    command = commands.add_parser("photographs", help="The photographs a farmer confirms")
    command.add_argument("located", type=Path, nargs="+", help="Written by multicam_fill")
    command.add_argument("--footage", type=Path, required=True, help="Written by fetch")
    command.add_argument("--per-walk", type=int, default=8)
    command.add_argument("--width", type=int, default=1280, help="Of the analysed picture")
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("frames", help="One session's pictures")
    command.add_argument("video", choices=sorted(SESSIONS))
    command.add_argument("output", type=Path)
    command.add_argument("--footage", type=Path, required=True, help="Written by fetch")
    command.add_argument("--width", type=int, default=1280)
    command = commands.add_parser("labels", help="The publisher's cows in a session's pictures")
    command.add_argument("frames", type=Path, help="Written by frames")
    command.add_argument("--located", type=Path, required=True, help="Written by multicam_fill")
    command.add_argument("--labels", type=Path, required=True, help="Folder of label folders")
    for name in ("track", "run", "score"):
        commands.add_parser(name, add_help=False, help=f"As app_{name}, with this farm's sessions")
    arguments, rest = parser.parse_known_args()
    if arguments.command in ("track", "run", "score"):
        sys.argv = [f"app_{arguments.command}.py", *rest]
        importlib.import_module(f"app_{arguments.command}").main()
    else:
        {"fetch": fetch, "photographs": photographs, "frames": frames, "labels": labels}[
            arguments.command
        ](arguments)


if __name__ == "__main__":
    main()
