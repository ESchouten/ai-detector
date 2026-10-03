"""Classify residual box errors geometrically; these labels are review hints."""

import argparse
import json
from collections import Counter
from pathlib import Path

from benchmark import digest, write_json
from video_assessment import pair_boxes

from aidetector.domain.models import BoundingBox


def overlaps(box, truth):
    values = []
    box_area = (box.x2 - box.x1) * (box.y2 - box.y1)
    for item in truth:
        x1, y1, x2, y2 = item["box"]
        area = (x2 - x1) * (y2 - y1)
        intersection = max(0, min(box.x2, x2) - max(box.x1, x1)) * max(
            0, min(box.y2, y2) - max(box.y1, y1)
        )
        values.append(
            {
                "cow": item["cow"],
                "iou": intersection / (box_area + area - intersection),
                "truth_covered": intersection / area,
                "relative_area": box_area / area,
            }
        )
    return values


def category(values):
    if any(row["iou"] >= 0.5 for row in values):
        return "duplicate_like"
    if sum(row["truth_covered"] >= 0.6 for row in values) >= 2:
        return "spans_multiple_cows"
    if any(row["iou"] >= 0.1 for row in values):
        return "partial_or_loose"
    return "little_annotation_overlap"


def assess(tracking):
    counts, samples = Counter(), {}
    for frame in tracking["timeline"]:
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        matched = pair_boxes(boxes, frame["truth"])
        counts["predictions"] += len(boxes)
        counts["matched"] += len(matched)
        for index, box in enumerate(boxes):
            if index in matched:
                continue
            values = overlaps(box, frame["truth"])
            kind = category(values)
            counts[kind] += 1
            selected = samples.setdefault(kind, [])
            if len(selected) < 5 and all(
                frame["second"] - row["second"] >= 20 for row in selected
            ):
                selected.append(
                    {
                        "second": frame["second"],
                        "box_index": index,
                        "box": frame["boxes"][index],
                        "overlaps": values,
                    }
                )
    total = counts["predictions"] - counts["matched"]
    return {
        "counts": dict(counts),
        "unmatched": total,
        "unmatched_fractions": {
            name: counts[name] / total if total else 0.0
            for name in (
                "duplicate_like",
                "spans_multiple_cows",
                "partial_or_loose",
                "little_annotation_overlap",
            )
        },
        "review_samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "scope": "Geometric error audit; no mask ground truth or recognition claims",
        "rules": "Unmatched boxes: duplicate IoU>=.5 first; then >=60% coverage of at least two annotations; then IoU>=.1 partial/loose; otherwise little overlap",
        "tracking_sha256": digest(args.tracking),
        **assess(json.loads(args.tracking.read_text())),
    }
    write_json(args.output, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "review_samples"}
        )
    )


if __name__ == "__main__":
    main()
