"""Compare directional and symmetric crop gates on cached actual detections."""

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_errors import category, overlaps
from video_assessment import pair_boxes

from aidetector.domain.models import BoundingBox


def overlap_scores(box, others):
    area = (box.x2 - box.x1) * (box.y2 - box.y1)
    symmetric, own = 0.0, 0.0
    for other in others:
        if other is box:
            continue
        intersection = max(0, min(box.x2, other.x2) - max(box.x1, other.x1)) * max(
            0, min(box.y2, other.y2) - max(box.y1, other.y1)
        )
        other_area = (other.x2 - other.x1) * (other.y2 - other.y1)
        symmetric = max(symmetric, intersection / min(area, other_area))
        own = max(own, intersection / area)
    return {"symmetric": symmetric, "own": own}


def assess(tracking, width, height):
    totals, geometry = Counter(), Counter()
    accepted = {
        f"{mode}-{threshold}": Counter()
        for mode in ("symmetric", "own")
        for threshold in (0.2, 0.3, 0.5)
    }
    for frame in tracking["timeline"]:
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        matched = pair_boxes(boxes, frame["truth"])
        for index, box in enumerate(boxes):
            values = overlaps(box, frame["truth"])
            spans = sum(row["truth_covered"] >= 0.6 for row in values) >= 2
            if index in matched:
                cow = frame["truth"][matched[index]]["cow"]
                groups = ["matched_known" if cow in range(1, 7) else "matched_unknown"]
            else:
                groups = ["unmatched", f"unmatched_{category(values)}"]
                if spans:
                    groups.append("unmatched_spans_multiple")
            if spans:
                groups.append("all_spans_multiple")
            totals.update(groups)
            if (
                box.x1 < 1
                or box.y1 < 1
                or box.x2 >= width - 1
                or box.y2 >= height - 1
                or min(box.x2 - box.x1, box.y2 - box.y1) < 64
            ):
                continue
            geometry.update(groups)
            for mode, value in overlap_scores(box, boxes).items():
                for threshold in (0.2, 0.3, 0.5):
                    if value <= threshold:
                        accepted[f"{mode}-{threshold}"].update(groups)
    return {
        "totals": dict(totals),
        "after_size_and_border_gate": dict(geometry),
        "accepted": {key: dict(value) for key, value in accepted.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tracking", "video", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    tracking = json.loads(args.tracking.read_text())
    if digest(args.video) != tracking["provenance"]["video"]:
        parser.error("Video does not match tracking provenance")
    capture = cv2.VideoCapture(str(args.video))
    width, height = (
        int(capture.get(key))
        for key in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)
    )
    capture.release()
    result = {
        "scope": "Cached crop-eligibility diagnostic; no recognition or runtime change",
        "tracking_sha256": digest(args.tracking),
        "width": width,
        "height": height,
        "min_crop_size": 64,
        "merged_hint": "Covers at least 60% of two publisher boxes; not verified mask evidence",
        **assess(tracking, width, height),
    }
    write_json(args.output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
