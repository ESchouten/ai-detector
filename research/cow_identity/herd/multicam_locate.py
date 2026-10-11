"""Find the publisher's pictures of MultiCamCows2024 again in the cameras' footage.

The publisher cut every cow out of one frame in five and turned her, and says
which cow each picture shows but not which frame it came from. A picture is
the frame's own pixels, so it can be laid back: details of the picture are
matched with details of a frame, a turn and a shift are fitted to them, and
the frame under the picture is compared with the picture grey level by grey
level. Every frame that a picture fits closely is kept: a cow that stands
still fits a row of frames equally well, and `multicam_fill` gives each of her
pictures one of them, in the order the pictures were taken.

That gives every published picture a frame and a place in it, which is what a
name shown on that footage is judged against.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

import multicam

# One frame in five carries a picture.
STEP = multicam.FILMED // multicam.RATE
# A picture and its own frame differ by 5 to 8 grey levels, and by more beside it.
CLOSE = 12
# Details that have to agree on one turn and shift before the pixels are compared.
AGREEING = 8
# One picture in five is looked for in every frame; the others are followed from it.
ANCHORS = 5
# Frames a walk may skip: the publisher threw out pictures in which cows overlap.
SKIPPED = 10
# A cow that walks by covers this many of the 57,600 points of a frame shrunk to 320 by 180.
LARGE = 1000
DETAILS = cv2.SIFT_create(nfeatures=500)
# Details kept of the part of a frame that changed: this many, and more of a part larger
# than a million points, in proportion.
FEW, DENSITY = 3000, 2500


def details(grey, finder=DETAILS):
    """Where a picture's details lie and how each looks; whole numbers, kept as bytes."""
    points, described = finder.detectAndCompute(grey, None)
    if described is None:
        return np.empty((0, 2), np.float32), np.empty((0, 128), np.uint8)
    return np.float32([point.pt for point in points]), described.astype(np.uint8)


def fitted(picture, frame):
    """The turn and shift that lay a picture's details onto a frame's, if enough agree."""
    if len(picture[1]) < 2 or len(frame[1]) < 2:
        return None
    pairs = [
        pair[0]
        for pair in cv2.BFMatcher().knnMatch(picture[1], frame[1], k=2)
        if pair[0].distance < 0.75 * pair[1].distance
    ]
    if len(pairs) < AGREEING:
        return None
    transform, agreeing = cv2.estimateAffinePartial2D(
        np.float32([picture[0][pair.queryIdx] for pair in pairs]),
        np.float32([frame[0][pair.trainIdx] for pair in pairs]),
        ransacReprojThreshold=3,
    )
    if transform is None or agreeing.sum() < AGREEING:
        return None
    scale = np.hypot(transform[0, 0], transform[1, 0])
    return transform if 0.95 < scale < 1.05 else None


def difference(frame, picture, transform):
    """Mean grey-level difference between a picture and the frame laid under it."""
    height, width = picture.shape
    under = cv2.warpAffine(frame, cv2.invertAffineTransform(transform), (width, height))
    return float(np.abs(under.astype(np.int16) - picture.astype(np.int16)).mean())


def corners(transform, width, height):
    """Where a picture's four corners lie in the frame."""
    square = np.array([[0, 0, 1], [width, 0, 1], [width, height, 1], [0, height, 1]])
    return (square @ transform.T).round(1).tolist()


def sampled(clip):
    """A clip's frames that may carry a picture, in grey, with their numbers."""
    for number, image in multicam.kept_frames(clip):
        yield number, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def usual(clip):
    """What a clip mostly shows, shrunk: the median of sixty frames spread over it.

    Haze and daylight drift over a session, so a frame is compared with its own clip. A cow
    walks through and leaves no trace in the median.
    """
    capture = cv2.VideoCapture(str(clip))
    small = []
    for number in np.linspace(0, capture.get(cv2.CAP_PROP_FRAME_COUNT) - 1, 60).astype(int):
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(number))
        grey = cv2.cvtColor(capture.read()[1], cv2.COLOR_BGR2GRAY)
        small.append(cv2.resize(grey, (320, 180)))
    return np.median(small, axis=0)


def moved(grey, passage):
    """The details of the parts of a frame in which something as large as a cow has changed.

    Nothing when the frame shows the passage as it usually is. Cows in the pens beside the
    passage move too, but show less of themselves than a cow that walks by. The details are
    taken at the frame's full size: at half its size the faint marks of a nearly plain cow
    are lost.
    """
    changed = np.abs(cv2.resize(grey, (320, 180)).astype(np.int16) - passage) > 20
    _, _, blobs, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8))
    scale = grey.shape[1] // 320
    points, described = [], []
    for left, top, width, height, area in blobs[1:]:
        if area >= LARGE:
            left, top = max(0, left - 12) * scale, max(0, top - 12) * scale
            part = grey[top : top + (height + 24) * scale, left : left + (width + 24) * scale]
            finder = cv2.SIFT_create(nfeatures=max(FEW, part.size * DENSITY // 1_000_000))
            found, told = details(part, finder)
            points.append(found + np.float32([left, top]))
            described.append(told)
    return (np.concatenate(points), np.concatenate(described)) if points else None


def followed(walk, start, at, frames, described):
    """A walk's pictures tried on the frames after and before one that was found."""
    tried = []
    for direction in (1, -1):
        position, last = start + direction, at
        while 0 <= position < len(walk):
            found = []
            for skipped in range(1, SKIPPED + 2):
                number = last + direction * skipped * STEP
                if number in frames:
                    transform = fitted(described(walk[position]), frames[number])
                    if transform is not None:
                        found.append((position, number, transform))
            if not found:
                break
            tried += found
            last = found[0][1]
            position += direction
    return tried


def locate(arguments):
    walks = [
        walk["files"]
        for walk in multicam.walks(arguments.pictures, (arguments.day,), multicam.COWS)
        if walk["camera"] == arguments.camera
    ]
    kept = {}

    def described(file):
        if file not in kept:
            kept[file] = details(cv2.imread(str(file), cv2.IMREAD_GRAYSCALE))
        return kept[file]

    anchors = [(walk, position) for walk in walks for position in range(0, len(walk), ANCHORS)]
    told = [described(walk[position])[1] for walk, position in anchors]
    owner = np.concatenate([np.full(len(each), anchor) for anchor, each in enumerate(told)])
    index = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 4}, {"checks": 64})
    index.add([np.concatenate(told).astype(np.float32)])
    index.train()
    fits, read = {}, {}
    for clip in multicam.clips(arguments.footage, arguments.day, arguments.camera):
        passage = usual(clip)
        frames = {}
        read[clip.name] = 0
        for number, grey in sampled(clip):
            read[clip.name] += 1
            seen = moved(grey, passage)
            if seen is not None:
                frames[number] = seen
        # Each frame votes for the anchors its details resemble; the best frames of an anchor
        # are tried, and the walk is followed from wherever the anchor fits.
        votes = defaultdict(list)
        for number, (_, seen) in frames.items():
            if len(seen) == 0:
                continue
            nearest = [pair[0].trainIdx for pair in index.knnMatch(seen.astype(np.float32), k=1)]
            counted = np.bincount(owner[nearest], minlength=len(anchors))
            for anchor in np.flatnonzero(counted >= AGREEING):
                votes[anchor].append((int(counted[anchor]), number))
        tried, reached = [], set()
        for anchor in sorted(votes, key=lambda anchor: max(votes[anchor]), reverse=True):
            walk, position = anchors[anchor]
            if walk[position] in reached:
                continue
            for _, number in sorted(votes[anchor], reverse=True)[:5]:
                transform = fitted(described(walk[position]), frames[number])
                if transform is not None:
                    chain = [(position, number, transform)]
                    chain += followed(walk, position, number, frames, described)
                    tried += [(walk[other], frame, turn) for other, frame, turn in chain]
                    reached.update(walk[other] for other, _, _ in chain)
                    break
        wanted = defaultdict(list)
        for file, number, transform in tried:
            wanted[number].append((file, transform))
        for number, grey in sampled(clip):
            for file, transform in wanted.get(number, ()):
                picture = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
                apart = difference(grey, picture, transform)
                fit = fits.setdefault(file, {}).get((clip.name, number))
                if apart < CLOSE and (fit is None or apart < fit["difference"]):
                    fits[file][clip.name, number] = {
                        "cow": int(file.parent.name),
                        "picture": file.name,
                        "clip": clip.name,
                        "frame": number,
                        "corners": corners(transform, picture.shape[1], picture.shape[0]),
                        "difference": round(apart, 2),
                    }
        print(
            clip.name,
            len(frames),
            "frames with a cow,",
            sum(bool(found) for found in fits.values()),
            "pictures found so far",
            flush=True,
        )
    pictures = [file for walk in walks for file in walk]
    found = sum(bool(fits.get(file)) for file in pictures)
    arguments.output.write_text(
        json.dumps(
            {
                "day": arguments.day,
                "camera": arguments.camera,
                "frames_read": read,
                "pictures": len(pictures),
                "found": found,
                "fits": [fit for file in pictures for fit in fits.get(file, {}).values()],
            }
        )
        + "\n"
    )
    print(arguments.day, arguments.camera, found, "of", len(pictures), "pictures found")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pictures", type=Path, help="MultiCamCows2024Root")
    parser.add_argument("footage", type=Path, help="Written by multicam.py fetch")
    parser.add_argument("--day", choices=multicam.DAYS, required=True)
    parser.add_argument("--camera", type=int, choices=multicam.CAMERAS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    locate(parser.parse_args())


if __name__ == "__main__":
    main()
