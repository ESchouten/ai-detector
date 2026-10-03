"""Reveal all cached outputs on a frozen geometry sample; never rescore names."""

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import lap
import numpy as np
from benchmark import digest, write_json
from detection_cutie_variants import largest_components
from video_assessment import annotations, pixels_hash, truth_at

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03"
CLEAN = Path(".cache/cow-geometry-audit")
RUN = Path(".cache/cow-cutie/streaming-reserved")
OUTPUT = CLEAN / "revealed"
FILES = {
    "protocol": ROOT / "annotation_geometry_protocol.json",
    "clean_manifest": CLEAN / "manifest.json",
    "audit_review": RESULTS / "geometry-review-audit.json",
    "cattle_review": RESULTS / "geometry-review-cattle.json",
    "comparison": RESULTS / "geometry-review-comparison.json",
    "adjudication": RESULTS / "geometry-review-adjudication.json",
    "streaming": RUN / "streaming.json",
    "annotations": Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    "source_pickle": Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
}
COLORS = np.asarray(
    [
        (0, 0, 0),
        (0, 80, 255),
        (0, 255, 140),
        (255, 100, 0),
        (180, 0, 220),
        (0, 230, 255),
        (220, 220, 0),
        (150, 120, 255),
        (70, 210, 100),
    ],
    dtype=np.uint8,
)


def xyxy(box):
    return [box[key] for key in ("x1", "y1", "x2", "y2")]


def area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def overlap(first, second):
    common = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1])
    )
    return common / (area(first) + area(second) - common)


def compare_geometry(review, publisher):
    """Anonymous extent comparison, including uncertain and adjudicated errors."""
    values = np.asarray(
        [[overlap(a["box"], b["box"]) for b in publisher] for a in review]
    )
    _, matches, _ = lap.lapjv(-values, extend_cost=True)
    pairs = []
    for index, target in enumerate(matches):
        if target < 0 or values[index, target] == 0:
            continue
        before, after = review[index], publisher[target]
        pairs.append(
            {
                "review_local_id": before["local_id"],
                "publisher_cow": after["cow"],
                "review_uncertain": before["uncertain"],
                "iou": float(values[index, target]),
                "publisher_to_review_area_ratio": area(after["box"])
                / area(before["box"]),
            }
        )
    return pairs


def rectangle(image, bounds, color, label):
    points = [int(value) for value in bounds]
    cv2.rectangle(image, tuple(points[:2]), tuple(points[2:]), color, 1)
    cv2.putText(
        image,
        label,
        (points[0], max(12, points[1] - 3)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        color,
        1,
        cv2.LINE_AA,
    )


def title(image, text):
    result = cv2.copyMakeBorder(
        image, 28, 0, 0, 0, cv2.BORDER_CONSTANT, value=(250, 250, 250)
    )
    cv2.putText(
        result,
        text,
        (8, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (10, 10, 10),
        1,
        cv2.LINE_AA,
    )
    return result


def render(second, source, audit, cattle, publisher, frame, mask):
    reviewers, truth, foreground, detector = [source.copy() for _ in range(4)]
    for prefix, rows, color in (
        ("A", audit, (255, 180, 0)),
        ("C", cattle, (0, 230, 255)),
    ):
        for row in rows:
            rectangle(
                reviewers,
                row["box"],
                color,
                prefix + row["local_id"] + ("?" if row["uncertain"] else ""),
            )
    for row in publisher:
        rectangle(truth, row["box"], (0, 255, 0), f"Publisher {row['cow']}")
    nonzero = mask > 0
    foreground[nonzero] = (
        foreground[nonzero] * 0.65 + COLORS[mask[nonzero]] * 0.35
    ).astype(np.uint8)
    for box in frame["boxes"]:
        slot = box["track_id"]
        named = slot in frame["named_track_ids"]
        rectangle(
            foreground,
            xyxy(box),
            tuple(int(x) for x in COLORS[slot + 1]),
            f"{'Name' if named else 'slot'} {slot + 1}",
        )
    for index, box in enumerate(frame["raw_detector_boxes"]):
        rectangle(detector, xyxy(box), (255, 180, 0), f"Proposal {index}")
    panels = [
        title(
            reviewers,
            f"{second}s | Frozen anonymous reviews A:cyan C:yellow; ?:uncertain",
        ),
        title(truth, "Unchanged publisher rectangles; numbers are publisher labels"),
        title(
            foreground,
            "All original indexed masks + emitted LCC boxes; Name=recorded decision",
        ),
        title(
            detector,
            "All same-frame raw YOLO proposals, including unnamed/duplicate boxes",
        ),
    ]
    for key, panel in zip(
        ("reviews", "publisher", "mask", "detector"), panels, strict=True
    ):
        if not cv2.imwrite(str(OUTPUT / f"{second}-{key}.png"), panel):
            raise OSError("Could not save diagnostic panel")
    montage = np.vstack((np.hstack(panels[:2]), np.hstack(panels[2:])))
    if not cv2.imwrite(str(OUTPUT / f"{second}.jpg"), montage):
        raise OSError("Could not save diagnostic montage")


def read_inputs():
    data = {
        key: json.loads(path.read_text())
        for key, path in FILES.items()
        if path.suffix == ".json"
    }
    for review in (data["audit_review"], data["cattle_review"]):
        if review["protocol_sha256"] != digest(FILES["protocol"]) or review[
            "source_manifest_sha256"
        ] != digest(FILES["clean_manifest"]):
            raise ValueError("Review provenance changed")
    for path, expected in data["adjudication"]["sources"].items():
        if digest(Path(path)) != expected:
            raise ValueError("A pre-reveal review changed")
    seconds = data["protocol"]["seconds"]
    if len(seconds) != 20 or max(seconds) >= 3000:
        raise ValueError("Only the frozen 20 exposed centers may be revealed")
    return data, seconds


def checked_images(second, frame, item):
    source = cv2.imread(item["path"])
    if (
        digest(Path(item["path"])) != item["sha256"]
        or pixels_hash(source) != frame["source_pixels_sha256"]
    ):
        raise ValueError("Model/reviewer source pixels differ")
    if frame["publisher_frame"] != item["video_frame"] + 1:
        raise ValueError("Publisher frame alignment differs")
    path = RUN / "masks" / f"{second}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Cached model mask changed")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if mask.shape != (600, 800) or mask.dtype != np.uint8 or mask.max() > 8:
        raise ValueError("Unexpected cached mask geometry")
    return source, mask


def main():
    data, seconds = read_inputs()
    clean = {row["second"]: row for row in data["clean_manifest"]["rows"]}
    frames = {
        row["second"]: row
        for row in data["streaming"]["timeline"]
        if row["second"] in seconds
    }
    reviews = {
        key: {row["second"]: row["objects"] for row in data[key]["frames"]}
        for key in ("audit_review", "cattle_review")
    }
    records, _ = annotations(SimpleNamespace(**FILES))
    OUTPUT.mkdir(exist_ok=False)
    details = []
    for second in seconds:
        frame, item = frames[second], clean[second]
        source, mask = checked_images(second, frame, item)
        _, components = largest_components(mask)
        publisher = truth_at(records, frame["publisher_frame"], 800, 600)
        audit, cattle = (
            reviews[key][second] for key in ("audit_review", "cattle_review")
        )
        render(second, source, audit, cattle, publisher, frame, mask)
        details.append(
            {
                "second": second,
                "publisher": publisher,
                "audit_geometry": compare_geometry(audit, publisher),
                "cattle_geometry": compare_geometry(cattle, publisher),
                "recorded_model_outputs": frame,
                "mask_components": components,
            }
        )
    result = {
        "scope": "All frozen sample centers revealed only after both anonymous reviews and raw-only adjudication froze. Descriptive extent comparison, not alternative model accuracy, replacement truth or a passing score.",
        "association": "Maximum summed anonymous rectangle IoU, zero-overlap matches omitted. Publisher cow numbers are stored as provenance, not independently verified biological identities.",
        "files": {str(path): digest(path) for path in FILES.values()},
        "implementation_sha256": digest(Path(__file__)),
        "frames": details,
    }
    write_json(RESULTS / "geometry-review-reveal.json", result)
    print(json.dumps({"centers": len(details), "panels": str(OUTPUT)}))


if __name__ == "__main__":
    main()
