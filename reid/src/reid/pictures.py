"""Which of a track's pictures to compare: ways of choosing, tested without labels.

`pictures_from_video` keeps every tracked cow picture of a farm video, with
what can be told about it on the spot: its size, whether it touches the frame's
edge or hides under another box, and the shape of its segmentation mask.
`compare` then cuts the tracks into short windows, each standing in for a
sighting, and lets each way of choosing pick a window's pictures. Two windows
of one track a while apart are the same cow; windows of tracks in view at the
same moment are different cows. A better choice makes the first look more alike
than the second.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.tracking import COCO_COW, Detection, cut

# Smaller pictures carry too little coat; the same floor as ai-detector's.
SIDE_MIN = 48
# Pictures a sighting keeps, as in ai-detector.
COUNT = 4
# ai-detector counts a picture as hidden when one other box covers this much.
COVERED = 0.25
EDGE = 2
# Parts of a mask smaller than this share of it are specks, not pieces.
SPECK = 0.05


@dataclass(frozen=True)
class Picture:
    """One tracked cow in one frame, and how whole it looks."""

    path: Path
    track: str
    frame: int
    seconds: float
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    edge: bool
    # The largest share of the box under any one other box.
    overlap: float
    # The mask's area over its convex hull's: low when rails cut it up or it
    # holds two cows.
    solidity: float
    # Separate parts of the mask.
    pieces: int
    # The mask's area over its own bounding box's.
    fill: float

    @property
    def area(self) -> int:
        return (self.x2 - self.x1) * (self.y2 - self.y1)

    @property
    def clear(self) -> bool:
        """Away from the edge and not hidden under another box: ai-detector's
        whole picture."""
        return not self.edge and self.overlap <= COVERED


def shape(mask: NDArray[np.bool_]) -> tuple[float, int, float]:
    """A mask's solidity, its pieces, and how much of its own box it fills."""
    import cv2

    inside = mask.astype(np.uint8)
    total = int(inside.sum())
    if total == 0:
        return 0.0, 0, 0.0
    _, _, stats, _ = cv2.connectedComponentsWithStats(inside, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    pieces = int((areas >= SPECK * total).sum())
    contours = cv2.findContours(inside, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    hull = cv2.convexHull(np.concatenate(contours))
    # Hull corners sit on pixel centres, so a filled mask can come out a bit
    # larger than its hull.
    solidity = min(1.0, total / max(cv2.contourArea(hull), 1.0))
    ys, xs = np.nonzero(inside)
    box = (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)
    return solidity, pieces, total / box


def overlap(box: Detection, others: Sequence[Detection]) -> float:
    area = (box.x2 - box.x1) * (box.y2 - box.y1)
    largest = 0
    for other in others:
        if other is box:
            continue
        width = min(box.x2, other.x2) - max(box.x1, other.x1)
        height = min(box.y2, other.y2) - max(box.y1, other.y1)
        if width > 0 and height > 0:
            largest = max(largest, width * height)
    return largest / area if area > 0 else 1.0


def pictures_from_video(
    video: Path,
    out: Path,
    *,
    session: str,
    model: str = "yolo26m-seg.pt",
    every: int = 10,
    imgsz: int = 1280,
    confidence: float = 0.5,
    tracker: str = "botsort.yaml",
    device: str | None = None,
) -> list[Picture]:
    """Track cows through a video and keep every picture of every track.

    Pictures go to `<out>/<session>-<video>-<track>/<frame>.jpg`, grey outside
    the outline as the model sees them. Tracking runs on every `every`th frame,
    with ai-detector's tracker by default.
    """
    import cv2
    from ultralytics import YOLO

    detector = YOLO(model)
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    capture.release()
    pictures: list[Picture] = []
    results = detector.track(
        source=str(video),
        stream=True,
        persist=True,
        classes=[COCO_COW],
        conf=confidence,
        imgsz=imgsz,
        vid_stride=every,
        tracker=tracker,
        device=device,
        verbose=False,
    )
    for index, result in enumerate(results):
        boxes = result.boxes
        if boxes is None or boxes.id is None or result.masks is None:
            continue
        masks = result.masks.data.cpu().numpy() > 0.5
        detections = [
            Detection(
                int(track),
                *(int(round(value)) for value in xyxy),
                outline=result.masks.xy[row],
            )
            for row, (track, xyxy) in enumerate(
                zip(boxes.id.tolist(), boxes.xyxy.tolist(), strict=True)
            )
        ]
        scores = boxes.conf.tolist()
        height, width = result.orig_shape
        frame = index * every
        for row, detection in enumerate(detections):
            if min(detection.x2 - detection.x1, detection.y2 - detection.y1) < SIDE_MIN:
                continue
            name = f"{session}-{video.stem}-{detection.track}"
            path = out / name / f"{frame:07d}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), cut(result.orig_img, detection, True))
            solidity, pieces, fill = shape(masks[row])
            pictures.append(
                Picture(
                    path,
                    name,
                    frame,
                    frame / fps,
                    detection.x1,
                    detection.y1,
                    detection.x2,
                    detection.y2,
                    float(scores[row]),
                    detection.x1 <= EDGE
                    or detection.y1 <= EDGE
                    or detection.x2 >= width - EDGE
                    or detection.y2 >= height - EDGE,
                    overlap(detection, detections),
                    solidity,
                    pieces,
                    fill,
                )
            )
    return pictures


_COLUMNS = tuple(field.name for field in fields(Picture))


def write_pictures(path: Path, pictures: Sequence[Picture]) -> None:
    """A CSV of the pictures; their paths relative to its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(_COLUMNS)
        for picture in pictures:
            row = [getattr(picture, column) for column in _COLUMNS]
            if picture.path.is_relative_to(path.parent):
                row[0] = picture.path.relative_to(path.parent).as_posix()
            writer.writerow(row)


def read_pictures(path: Path) -> list[Picture]:
    types: dict[str, Callable[[str], Any]] = {
        "path": lambda text: path.parent / text,
        "track": str,
        "seconds": float,
        "confidence": float,
        "overlap": float,
        "solidity": float,
        "fill": float,
        "edge": lambda text: text == "True",
    }
    with path.open(newline="", encoding="utf-8") as file:
        return [
            Picture(**{key: types.get(key, int)(value) for key, value in row.items()})
            for row in csv.DictReader(file)
        ]


@dataclass(frozen=True)
class Choice:
    """A way of choosing a sighting's pictures: the best tier first, then the
    largest by `key`, spread over time as ai-detector does."""

    name: str
    tier: Callable[[Picture], int]
    key: Callable[[Picture], float]


def _box(picture: Picture) -> float:
    return picture.area


def _mask(picture: Picture) -> float:
    return picture.area * picture.fill


def _confidence(picture: Picture) -> float:
    return picture.confidence


def _clear(picture: Picture) -> int:
    return 0 if picture.clear else 1


def whole(solidity: float) -> Callable[[Picture], int]:
    """Clear pictures whose mask is one solid piece first, then clear ones."""

    def tier(picture: Picture) -> int:
        if picture.clear and picture.pieces == 1 and picture.solidity >= solidity:
            return 0
        return 1 if picture.clear else 2

    return tier


AI_DETECTOR = Choice("ai-detector", _clear, _box)


def choices(solidities: Sequence[float]) -> list[Choice]:
    """ai-detector's choice today, and ways that also look at the mask."""
    found = [
        Choice("any", lambda picture: 0, _box),
        AI_DETECTOR,
        Choice("ai-detector, mask area", _clear, _mask),
        Choice("ai-detector, confidence", _clear, _confidence),
    ]
    for solidity in solidities:
        found.append(Choice(f"one piece, solidity {solidity:g}", whole(solidity), _box))
        found.append(
            Choice(
                f"one piece, solidity {solidity:g}, mask area", whole(solidity), _mask
            )
        )
    return found


def choose(
    pictures: Sequence[Picture], choice: Choice, count: int = COUNT
) -> list[int]:
    """The indexes of the pictures a sighting keeps."""
    if not pictures:
        return []
    ranked = sorted(
        range(len(pictures)),
        key=lambda i: (choice.tier(pictures[i]), -choice.key(pictures[i])),
    )
    best = choice.tier(pictures[ranked[0]])
    pool = [i for i in ranked if choice.tier(pictures[i]) == best][: 2 * count]
    pool.sort(key=lambda i: pictures[i].seconds)
    picks = np.unique(np.linspace(0, len(pool) - 1, min(count, len(pool))).round())
    chosen = [pool[int(pick)] for pick in picks]
    rest = [i for i in ranked if choice.tier(pictures[i]) != best]
    return chosen + rest[: count - len(chosen)]


@dataclass(frozen=True)
class Window:
    """A stretch of one track standing in for a sighting."""

    track: str
    start: float
    end: float
    pictures: tuple[int, ...]


def windows(
    pictures: Sequence[Picture], seconds: float, least: int = 2
) -> list[Window]:
    """Each track cut into consecutive stretches of `seconds`."""
    by_track: dict[str, list[int]] = {}
    for index, picture in enumerate(pictures):
        by_track.setdefault(picture.track, []).append(index)
    found = []
    for track, indexes in by_track.items():
        indexes.sort(key=lambda i: pictures[i].seconds)
        start = pictures[indexes[0]].seconds
        stretches: dict[int, list[int]] = {}
        for i in indexes:
            stretches.setdefault(
                int((pictures[i].seconds - start) // seconds), []
            ).append(i)
        for number, members in sorted(stretches.items()):
            if len(members) >= least:
                found.append(
                    Window(
                        track,
                        start + number * seconds,
                        start + (number + 1) * seconds,
                        tuple(members),
                    )
                )
    return found


def _seen_together(pictures: Sequence[Picture]) -> dict[str, set[str]]:
    """The other tracks each track shared a frame with: other cows."""
    frames: dict[int, set[str]] = {}
    for picture in pictures:
        frames.setdefault(picture.frame, set()).add(picture.track)
    together: dict[str, set[str]] = {}
    for tracks in frames.values():
        for track in tracks:
            together.setdefault(track, set()).update(tracks - {track})
    return together


def pairs(
    pictures: Sequence[Picture], found: Sequence[Window], gap: float
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Window pairs of the same cow and of different cows.

    Each window is paired with the latest window of its track that started at
    least `gap` seconds earlier, and with the windows of tracks seen in the same
    frame as its own during its stretch.
    """
    together = _seen_together(pictures)
    by_track: dict[str, list[int]] = {}
    for index, window in enumerate(found):
        by_track.setdefault(window.track, []).append(index)
    same, different = [], []
    for index, window in enumerate(found):
        earlier = [
            other
            for other in by_track[window.track]
            if found[other].start <= window.start - gap
        ]
        if earlier:
            same.append((index, max(earlier, key=lambda other: found[other].start)))
        for track in together.get(window.track, ()):
            for other in by_track.get(track, ()):
                if found[other].start < window.end and window.start < found[other].end:
                    if index < other:
                        different.append((index, other))
    return same, different


def _sightings(
    pictures: Sequence[Picture],
    vectors: NDArray[np.float32],
    found: Sequence[Window],
    choice: Choice,
) -> tuple[NDArray[np.float32], NDArray[np.bool_]]:
    """Each window's mean embedding of the chosen pictures, and whether the
    choice found a picture of its best tier there."""
    means = np.empty((len(found), vectors.shape[1]), np.float32)
    best = np.empty(len(found), bool)
    for row, window in enumerate(found):
        members = [pictures[i] for i in window.pictures]
        chosen = [window.pictures[i] for i in choose(members, choice)]
        mean = vectors[chosen].mean(axis=0)
        means[row] = mean / np.linalg.norm(mean)
        best[row] = choice.tier(pictures[chosen[0]]) == 0
    return means, best


def _verification(same: NDArray[np.float32], different: NDArray[np.float32]):
    """Share of same-cow pairs above the score only 1% of different-cow pairs
    reach, and the chance a same-cow pair outscores a different-cow pair."""
    if not len(same) or not len(different):
        return None, None
    floor = float(np.quantile(different, 0.99))
    ranks = np.searchsorted(np.sort(different), same, side="left")
    return float((same > floor).mean()), float(ranks.mean() / len(different))


def compare(
    pictures: Sequence[Picture],
    vectors: NDArray[np.float32],
    choices: Sequence[Choice],
    *,
    window: float = 10.0,
    gap: float = 60.0,
    solidity: float = 0.8,
) -> dict[str, Any]:
    found = windows(pictures, window)
    same, different = pairs(pictures, found, gap)
    rivals: dict[int, list[int]] = {}
    for a, b in different:
        rivals.setdefault(a, []).append(b)
        rivals.setdefault(b, []).append(a)
    results = []
    for choice in choices:
        means, best = _sightings(pictures, vectors, found, choice)
        same_scores = np.array([means[a] @ means[b] for a, b in same], np.float32)
        different_scores = np.array(
            [means[a] @ means[b] for a, b in different], np.float32
        )
        kept, auc = _verification(same_scores, different_scores)
        first = [
            float(means[a] @ means[b])
            > max(float(means[a] @ means[r]) for r in rivals[a])
            for a, b in same
            if a in rivals
        ]
        results.append(
            {
                "choice": choice.name,
                "best_found": float(best.mean()) if len(best) else None,
                "kept_at_1pct": kept,
                "auc": auc,
                "rank1": float(np.mean(first)) if first else None,
                "queries": len(first),
            }
        )
    return {
        "pictures": len(pictures),
        "tracks": len({picture.track for picture in pictures}),
        "windows": len(found),
        "same_pairs": len(same),
        "different_pairs": len(different),
        "window": window,
        "gap": gap,
        "choices": results,
        "features": features(pictures, vectors, found, same, rivals),
        "later": later(pictures, found, whole(solidity)),
    }


def _bucket(value: float, edges: Sequence[float]) -> str:
    for low, high in zip(edges, edges[1:], strict=False):
        if value < high:
            return f"{low:g}-{high:g}"
    return f"{edges[-1]:g}+"


def features(
    pictures: Sequence[Picture],
    vectors: NDArray[np.float32],
    found: Sequence[Window],
    same: Sequence[tuple[int, int]],
    rivals: dict[int, list[int]],
) -> dict[str, list[dict[str, Any]]]:
    """How single pictures fare by what is known of them.

    Each picture of a window with an earlier window of its cow and rivals in
    view is compared with those windows' sightings (ai-detector's choice). Its
    margin is its score for its own cow less its best score for a rival.
    """
    means, _ = _sightings(pictures, vectors, found, AI_DETECTOR)
    largest: dict[str, int] = {}
    for picture in pictures:
        largest[picture.track] = max(largest.get(picture.track, 0), picture.area)
    measures: dict[str, Callable[[Picture], str]] = {
        "pieces": lambda p: "3+" if p.pieces >= 3 else str(p.pieces),
        "solidity": lambda p: _bucket(p.solidity, (0, 0.6, 0.7, 0.8, 0.9)),
        "fill": lambda p: _bucket(p.fill, (0, 0.4, 0.5, 0.6, 0.7)),
        "clear": lambda p: "yes" if p.clear else "no",
        "confidence": lambda p: _bucket(p.confidence, (0, 0.6, 0.7, 0.8, 0.9)),
        "size of the track's largest": lambda p: _bucket(
            p.area / largest[p.track], (0, 0.5, 0.7, 0.9)
        ),
    }
    margins: dict[str, dict[str, list[float]]] = {name: {} for name in measures}
    for a, b in same:
        if a not in rivals:
            continue
        for index in found[a].pictures:
            vector = vectors[index] / np.linalg.norm(vectors[index])
            own = float(vector @ means[b])
            rival = max(float(vector @ means[r]) for r in rivals[a])
            for name, measure in measures.items():
                margins[name].setdefault(measure(pictures[index]), []).append(
                    own - rival
                )
    return {
        name: [
            {
                "value": value,
                "pictures": len(values),
                "first": float(np.mean(np.array(values) > 0)),
                "margin": float(np.mean(values)),
            }
            for value, values in sorted(buckets.items())
        ]
        for name, buckets in margins.items()
    }


def later(
    pictures: Sequence[Picture],
    found: Sequence[Window],
    tier: Callable[[Picture], int],
) -> dict[str, int]:
    """Tracks whose first window has no picture of the best tier, and of those,
    how many show one later: what saving a better sighting later would win."""
    first: dict[str, Window] = {}
    for window in found:
        if window.track not in first or window.start < first[window.track].start:
            first[window.track] = window
    tracks: dict[str, list[int]] = {}
    for index, picture in enumerate(pictures):
        tracks.setdefault(picture.track, []).append(index)
    lacking = [
        track
        for track, window in first.items()
        if all(tier(pictures[i]) > 0 for i in window.pictures)
    ]
    return {
        "tracks": len(first),
        "first_window_without_whole": len(lacking),
        "whole_later": sum(
            any(tier(pictures[i]) == 0 for i in tracks[track]) for track in lacking
        ),
    }
