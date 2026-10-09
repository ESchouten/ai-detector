"""A second farm: MmCows, read over the network a member at a time.

MmCows (https://huggingface.co/datasets/neis-lab/mmcows, CC BY-NC-SA 4.0)
films one pen of sixteen Holstein cows with four cameras for two weeks in
July 2023. One day, 25 July, carries a box and a number for every cow in
every fifteenth second, and every camera's picture of every second. The
archives hold hundreds of gigabytes, so only the members that are needed are
fetched, by range request.

Nothing of the herd method was developed on this farm. Its videos register
with the ETH index so that the same scripts run them: `run`, `track` and
`score` hand over to `app_run`, `app_track` and `app_score`.
"""

import argparse
import importlib
import io
import json
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

import ethz

# The dataset as it stood when this farm was measured.
REVISION = "310667084905487154b66b2fe5fbaa992cf55e3a"
SOURCE = f"https://huggingface.co/datasets/neis-lab/mmcows/resolve/{REVISION}/"
LABELLED = "visual_data.zip"
CAMERAS = (1, 2, 3, 4)
# The pictures are 4480 by 2800; labels are shares of that.
WIDTH, HEIGHT = 4480, 2800
# Barn time is five hours behind the timestamps in the file names.
ZONE = 5 * 3600
# The publisher's number for a cow that lies.
LYING = 7


class Remote(io.IOBase):
    """A read-only file over HTTP range requests, read in blocks that are kept.

    The publisher split its largest archives in parts; several names are read
    as the one file they make laid end to end.
    """

    def __init__(self, *names, block=1 << 20):
        self.session = requests.Session()
        self.parts = []
        self.size = 0
        for name in names:
            head = self.session.head(SOURCE + name, allow_redirects=True, timeout=60)
            head.raise_for_status()
            length = int(head.headers["Content-Length"])
            self.parts.append((SOURCE + name, self.size, length))
            self.size += length
        self.position = 0
        self.block = block
        self.blocks = {}

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (0, self.position, self.size)[whence] + offset
        return self.position

    def fetch(self, first, last):
        pieces = []
        for address, start, length in self.parts:
            low, high = max(first, start), min(last, start + length - 1)
            if low <= high:
                response = self.session.get(
                    address, headers={"Range": f"bytes={low - start}-{high - start}"}, timeout=300
                )
                response.raise_for_status()
                pieces.append(response.content)
        return b"".join(pieces)

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else count
        count = min(count, self.size - self.position)
        pieces = []
        while count > 0:
            number, offset = divmod(self.position, self.block)
            if number not in self.blocks:
                first = number * self.block
                self.blocks[number] = self.fetch(first, min(self.size, first + self.block) - 1)
            piece = self.blocks[number][offset : offset + count]
            pieces.append(piece)
            self.position += len(piece)
            count -= len(piece)
        return b"".join(pieces)

    def forget(self):
        """Drop the blocks behind the place being read; a walk through an archive would keep them all."""
        current = self.position // self.block
        self.blocks = {number: data for number, data in self.blocks.items() if number >= current}


def archive(*names, block=1 << 20):
    remote = Remote(*names, block=block)
    return zipfile.ZipFile(remote), remote


def stamp(member):
    """Seconds since 1970 from a picture or label name such as 1690308011_13-00-11.jpg."""
    return int(Path(member).name.split("_")[0])


def barn_time(seconds):
    return datetime.fromtimestamp(seconds - ZONE, UTC).replace(tzinfo=None)


def seconds_at(time):
    """The timestamp of a barn time on the annotated day, such as 14:00."""
    at = datetime.fromisoformat(f"{DAY}T{time}:00").replace(tzinfo=UTC)
    return int(at.timestamp()) + ZONE


DAY = "2023-07-25"
# The cows whose photographs are confirmed, and those that stay unknown: every fourth.
ENROLLED = (1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15)
WITHHELD = (4, 8, 12, 16)
# Photographs come from the hours before eight; a video starts four hours later at the earliest.
PHOTOGRAPHS = ("02:57", "08:00")
GAP_HOURS = 4
# A video is one camera's pictures from an hour on, named by that hour, and lasts so many minutes.
# Noon and two o'clock validate. Five and ten in the evening are the test: the herd is milked
# in between, and those hours stay unseen until a version passes validation.
MINUTES = {12: 30, 14: 60, 17: 60, 22: 60}
VIDEOS = {
    f"mmcows-{hour}00-cam{camera}": {
        "start": f"{DAY}T{hour}:00:00",
        "minutes": minutes,
        "camera": str(camera),
        "gap_hours": GAP_HOURS,
    }
    for hour, minutes in MINUTES.items()
    for camera in CAMERAS
}
# The herd scripts look their videos up in the ETH index.
ethz.VIDEOS.update(VIDEOS)


def window(video):
    """First second of a video and the first after it, as in the file names."""
    start, end = ethz.window(video)
    return seconds_at(f"{start:%H:%M}"), seconds_at(f"{end:%H:%M}")


def labelled_members(bundle, camera, kind="images", suffix=".jpg"):
    folder = "labels/combined" if kind == "labels" else "images"
    prefix = f"visual_data/{folder}/0725/cam_{camera}/"
    return sorted(
        name for name in bundle.namelist() if name.startswith(prefix) and name.endswith(suffix)
    )


def pen(bundle, camera):
    """Where the pen is in one camera's picture: the publisher blacked out everything else."""
    seen = np.zeros((HEIGHT, WIDTH), dtype=bool)
    for member in labelled_members(bundle, camera)[1450:1750:60]:
        image = cv2.imdecode(np.frombuffer(bundle.read(member), np.uint8), cv2.IMREAD_COLOR)
        seen |= image.max(axis=2) > 16
    # Black pixels inside the pen are shadows, not the mask: keep the outline's inside.
    outline, _ = cv2.findContours(seen.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    inside = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    cv2.drawContours(inside, [max(outline, key=cv2.contourArea)], -1, 255, cv2.FILLED)
    return inside


def boxes(text):
    """Publisher lines `cow x y w h`, centre and size as shares of the picture."""
    return [(int(cow), *map(float, rest)) for cow, *rest in map(str.split, text.splitlines())]


def photographs(arguments):
    """The publisher's boxes of some hours, cut out of the labelled pictures.

    Those of the early hours, one picture in eight, are the photographs a
    farmer confirms. Each is as large as the application's own picture shows
    the cow.
    """
    bundle, remote = archive(LABELLED)
    first, last = map(seconds_at, arguments.between)
    scale = arguments.width / WIDTH
    rows = []
    for camera in CAMERAS:
        wanted = [
            member for member in labelled_members(bundle, camera) if first <= stamp(member) < last
        ]
        for member in wanted[:: arguments.every]:
            at = barn_time(stamp(member))
            label = member.replace("/images/", "/labels/combined/").replace(".jpg", ".txt")
            image = cv2.imdecode(np.frombuffer(bundle.read(member), np.uint8), cv2.IMREAD_COLOR)
            for cow, x, y, w, h in boxes(bundle.read(label).decode()):
                left, top = max(0, round((x - w / 2) * WIDTH)), max(0, round((y - h / 2) * HEIGHT))
                right, bottom = round((x + w / 2) * WIDTH), round((y + h / 2) * HEIGHT)
                path = Path("photographs") / f"cow_{cow}" / f"{camera}-{stamp(member)}.jpg"
                target = arguments.output / path
                target.parent.mkdir(parents=True, exist_ok=True)
                cut = image[top:bottom, left:right]
                size = (max(1, round(cut.shape[1] * scale)), max(1, round(cut.shape[0] * scale)))
                cv2.imwrite(
                    str(target),
                    cv2.resize(cut, size, interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 95],
                )
                rows.append(
                    {
                        "path": str(path),
                        "cow": cow,
                        "camera": str(camera),
                        "date": at.strftime("%Y%m%d"),
                        "time": at.strftime("%H%M%S"),
                        "clip": f"{camera}-{at:%Y%m%d-%H%M%S}",
                    }
                )
    (arguments.output / "classification.json").write_text(json.dumps(rows) + "\n")
    print(len(rows), "photographs of", len({row["cow"] for row in rows}), "cows")


def frames(arguments):
    """One video's pictures, a second apart, with everything outside the pen blacked out.

    They are kept at the width the application analyses, and the publisher's
    labels of every fifteenth second go beside them in the ETH layout.
    """
    from aidetector.adapters.media.images import shrink_image

    camera = VIDEOS[arguments.video]["camera"]
    first, last = window(arguments.video)
    labelled, _ = archive(LABELLED)
    inside = pen(labelled, camera)
    labels = {
        stamp(member): labelled.read(member).decode()
        for member in labelled_members(labelled, camera, "labels", ".txt")
        if first <= stamp(member) < last
    }
    target = arguments.labels / arguments.video / "labels"
    target.mkdir(parents=True, exist_ok=True)
    for at, text in labels.items():
        (target / f"frame_{at:06d}.txt").write_text(text)
    arguments.output.mkdir(parents=True, exist_ok=True)
    index = []
    day = f"1s_interval_images/0725_cam_{camera}.zip.part."
    bundle, remote = archive(day + "aa", day + "ab", block=8 << 20)
    for member in sorted(bundle.namelist()):
        at = stamp(member)
        if not first <= at < last:
            continue
        image = cv2.imdecode(np.frombuffer(bundle.read(member), np.uint8), cv2.IMREAD_COLOR)
        remote.forget()
        image[inside == 0] = 0
        file = f"{at}.jpg"
        cv2.imwrite(
            str(arguments.output / file),
            shrink_image(image, arguments.width),
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )
        index.append(
            {"index": at, "seconds": float(at - first), "file": file, "labelled": at in labels}
        )
    (arguments.output / "frames.json").write_text(
        json.dumps({"video": arguments.video, "rate": 1.0, "frames": index}) + "\n"
    )
    print(arguments.video, len(index), "pictures,", len(labels), "of them labelled")


def behaviour(bundle, cow):
    """What the publisher saw a cow do in every second of the day, by timestamp."""
    lines = bundle.read(f"visual_data/behavior_labels/individual/C{cow:02d}_0725.csv").decode()
    return {
        int(second): float(doing)
        for second, _, doing in map(lambda line: line.split(","), lines.splitlines()[1:])
    }


def occasions(arguments):
    """Whether a cow can be in a video as she was photographed: lying on, in one stretch.

    For every cow this gives when she last changed what she did before each
    video, and how often she changed it since the last photograph.
    """
    bundle, _ = archive(LABELLED)
    last_photograph = seconds_at(PHOTOGRAPHS[1])
    starts = sorted({window(video)[0] for video in VIDEOS})
    result = {}
    for cow in sorted(ENROLLED + WITHHELD):
        doing = behaviour(bundle, cow)
        changes = [at for at in sorted(doing) if at - 1 in doing and doing[at] != doing[at - 1]]
        result[str(cow)] = {
            f"{barn_time(start):%H:%M}": {
                "lying": doing[start] == LYING,
                "unchanged_since": f"{barn_time(max(at for at in changes if at <= start)):%H:%M:%S}",
                "changes_since_the_last_photograph": sum(
                    last_photograph <= at <= start for at in changes
                ),
            }
            for start in starts
        }
    arguments.output.write_text(json.dumps(result, indent=1) + "\n")
    for start in starts:
        at = f"{barn_time(start):%H:%M}"
        print(
            at,
            "fewest changes of a cow since the last photograph:",
            min(cow[at]["changes_since_the_last_photograph"] for cow in result.values()),
            "| longest unchanged since:",
            min(cow[at]["unchanged_since"] for cow in result.values()),
        )


def postures(arguments):
    """Of the cows in a run's judged pictures, lying and on their feet: how many were found, and named.

    A run is what `run` or `track` wrote; a cow is found when one of the
    application's boxes was paired with hers.
    """
    from app_score import labelled_frames, paired
    from ethz import frame_labels

    bundle, _ = archive(LABELLED)
    doing = {cow: behaviour(bundle, cow) for cow in sorted(ENROLLED + WITHHELD)}
    result = {}
    for path in arguments.runs:
        run = json.loads(path.read_text())
        frames = arguments.frames / run["video"]
        counted, (partner, *_) = paired(run, frames, arguments.labels)
        shown = run.get("shown", [None] * len(run["boxes"]))
        found, named = set(), set()
        for position, cow in zip(counted, partner, strict=True):
            if cow is not None:
                found.add((run["boxes"][position]["index"], cow))
                if shown[position] == cow:
                    named.add((run["boxes"][position]["index"], cow))
        width, height = run["boxes"][0]["frame_size"]
        counts = Counter()
        for index in labelled_frames(frames):
            for cow, *_ in frame_labels(arguments.labels, run["video"], index, width, height):
                group = (
                    "enrolled" if cow in ENROLLED else "withheld",
                    "lying" if doing[cow][index] == LYING else "on_her_feet",
                )
                counts[(*group, "visible")] += 1
                counts[(*group, "found")] += (index, cow) in found
                counts[(*group, "named")] += (index, cow) in named
        result[path.name] = {
            f"{who}_{posture}": {
                what: counts[(who, posture, what)] for what in ("visible", "found", "named")
            }
            for who in ("enrolled", "withheld")
            for posture in ("lying", "on_her_feet")
        }
        for group, numbers in result[path.name].items():
            print(path.name, group, numbers)
    if arguments.output:
        arguments.output.write_text(json.dumps(result, indent=1) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    confirm = commands.add_parser("photographs", help="The photographs a farmer confirms")
    confirm.add_argument("output", type=Path)
    confirm.add_argument("--width", type=int, default=1280, help="Of the analysed picture")
    confirm.add_argument("--between", nargs=2, default=PHOTOGRAPHS, metavar="HH:MM")
    confirm.add_argument("--every", type=int, default=8, help="Eight is one every two minutes")
    cut = commands.add_parser("frames", help="One video's pictures and labels")
    cut.add_argument("video", choices=sorted(VIDEOS))
    cut.add_argument("output", type=Path)
    cut.add_argument("--labels", type=Path, required=True, help="Folder of label folders")
    cut.add_argument("--width", type=int, default=1280)
    apart = commands.add_parser("occasions", help="How long before a video each cow last moved on")
    apart.add_argument("output", type=Path)
    lying = commands.add_parser("postures", help="Lying and standing cows found and named in runs")
    lying.add_argument("runs", type=Path, nargs="+", help="JSON written by run or track")
    lying.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    lying.add_argument("--labels", type=Path, required=True)
    lying.add_argument("--output", type=Path)
    for name in ("track", "run", "score"):
        commands.add_parser(name, add_help=False, help=f"As app_{name}, with this farm's videos")
    arguments, rest = parser.parse_known_args()
    if arguments.command in ("track", "run", "score"):
        sys.argv = [f"app_{arguments.command}.py", *rest]
        importlib.import_module(f"app_{arguments.command}").main()
    else:
        {
            "photographs": photographs,
            "frames": frames,
            "occasions": occasions,
            "postures": postures,
        }[arguments.command](arguments)


if __name__ == "__main__":
    main()
