"""Index of the public ETH Zurich barn dataset (13 Holstein cows, 2023).

Source: https://doi.org/10.3929/ethz-c-000796658. The publisher's classification
crops carry the cow, camera and recording time in their file names; the tracking
videos carry one label file per frame whose class is the cow.
"""

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import cv2

CROP = re.compile(
    r"id_(?P<cow>\d+)_te31-57-(?P<camera>\d+)-(?P<date>\d{8})-(?P<time>\d{6})"
    r"(?:-\d+-\d+_(?P<frame>\d+)|_frame(?P<first>\d+))\.png$"
)

# First burned-in timestamp, length and camera of each tracking video.
VIDEOS = {
    "video1": {"start": "2023-08-27T17:55:26", "minutes": 5, "camera": "197"},
    "video2": {"start": "2023-08-26T04:11:36", "minutes": 5, "camera": "195"},
    "video3": {"start": "2023-08-25T14:48:55", "minutes": 30, "camera": "195"},
    "video4": {"start": "2023-08-24T20:18:36", "minutes": 30, "camera": "197"},
    "video5": {"start": "2023-09-17T13:29:37", "minutes": 60, "camera": "195"},
    "video6": {"start": "2023-08-28T01:19:36", "minutes": 60, "camera": "197"},
}
# A cow can lie in one place for hours, so photographs taken shortly before a
# video are near copies of it. Confirmed photographs must be a day older.
GAP = timedelta(hours=24)


# Videos kept out of development: 1 and 2 validate a drafted method, 5 and 6
# test the frozen one.
HELD_BACK = ("video1", "video2", "video5", "video6")


def gap(video):
    """How much older than a video its confirmed photographs must be: a day, unless it says otherwise."""
    return timedelta(hours=VIDEOS[video].get("gap_hours", GAP.total_seconds() / 3600))


def crop_time(row):
    return datetime.strptime(row["date"] + row["time"], "%Y%m%d%H%M%S")


def window(video):
    start = datetime.fromisoformat(VIDEOS[video]["start"])
    return start, start + timedelta(minutes=VIDEOS[video]["minutes"])


def near(row, video):
    """Whether a crop was recorded within a day of the video."""
    start, end = window(video)
    return start - GAP < crop_time(row) < end + GAP


def development_rows(rows):
    """Crops development may read: none within a day of a held-back video."""
    return [row for row in rows if not any(near(row, video) for video in HELD_BACK)]


def confirmed_before(rows, video, cows, either_side=False):
    """Publisher crops of `cows` that may teach a herd model used on `video`.

    The evaluation takes only crops at least a day older than the video.
    Development may also take crops at least a day after it (`either_side`),
    and then stays a day away from every held-back video as well.
    """
    start, _ = window(video)
    if either_side:
        return [
            row
            for row in development_rows(rows)
            if row["cow"] in cows and not near(row, video)
        ]
    return [row for row in rows if row["cow"] in cows and crop_time(row) <= start - gap(video)]


def classification_rows(root):
    """Every publisher crop below `root`, which contains `classification/`."""
    rows = []
    for path in sorted(Path(root).glob("classification/*/cow_*/*.png")):
        match = CROP.search(path.name)
        if match is None:
            raise ValueError(f"Unrecognised crop name: {path.name}")
        if int(path.parent.name.removeprefix("cow_")) != int(match["cow"]):
            raise ValueError(f"Folder and file disagree about the cow: {path}")
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "cow": int(match["cow"]),
                "camera": match["camera"],
                "date": match["date"],
                "time": match["time"],
                # One recorded clip; its crops of one cow count as one confirmation.
                "clip": f"{match['camera']}-{match['date']}-{match['time']}",
                "frame": int(match["frame"] or match["first"]),
                "publisher_split": path.parents[1].name,
            }
        )
    return rows


def sample_frames(root, video, interval, output):
    """Store one frame per `interval` seconds as JPEG, keeping its source index.

    Decoding is sequential from frame zero because the label files are numbered
    by decoded frame; seeking would not guarantee the same numbering.
    """
    capture = cv2.VideoCapture(str(Path(root) / video / f"{video}.mp4"))
    rate = capture.get(cv2.CAP_PROP_FPS)
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    wanted = {round(step * interval * rate): step for step in range(total)}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(total):
        if not capture.grab():
            break
        if index not in wanted:
            continue
        ok, image = capture.retrieve()
        if not ok:
            raise ValueError(f"Frame {index} of {video} could not be decoded")
        name = f"{index:06d}.jpg"
        cv2.imwrite(str(output / name), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        frames.append({"index": index, "seconds": index / rate, "file": name})
    capture.release()
    (output / "frames.json").write_text(
        json.dumps({"video": video, "rate": rate, "frames": frames}) + "\n"
    )
    return frames


DISPUTED = -1


def frame_labels(root, video, index, width, height):
    """Publisher boxes of one frame as (cow, x1, y1, x2, y2) in pixels.

    The publisher gave one cow two boxes in some frames; at most one can be
    right, so both carry DISPUTED instead of the cow and count nowhere.
    """
    boxes = []
    path = Path(root) / video / "labels" / f"frame_{index:06d}.txt"
    for line in path.read_text().splitlines():
        cow, x, y, w, h = line.split()
        x, y, w, h = float(x) * width, float(y) * height, float(w) * width, float(h) * height
        boxes.append((int(cow), x - w / 2, y - h / 2, x + w / 2, y + h / 2))
    seen = Counter(box[0] for box in boxes)
    return [(DISPUTED if seen[box[0]] > 1 else box[0], *box[1:]) for box in boxes]
