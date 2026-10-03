"""Describe failures in an existing seeded-propagation cache without inference."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from benchmark import digest, write_json
from detection_errors import assess, overlaps
from video_assessment import annotations, pair_boxes, truth_at

from aidetector.domain.models import BoundingBox


def audit(value, records):
    states = defaultdict(list)
    timeline = []
    seeds = value["provenance"]["seed_prompts"]
    for frame in value["timeline"]:
        truth = truth_at(records, frame["second"] * 20 + 1, 800, 600)
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        paired = pair_boxes(boxes, truth)
        for index, box in enumerate(boxes):
            cow = seeds[box.track_id]["cow"]
            actual = truth[paired[index]]["cow"] if index in paired else None
            values = overlaps(box, truth)
            best = max(values, key=lambda row: row["iou"])
            states[cow].append(
                {
                    "second": frame["second"],
                    "matched_cow": actual,
                    "best_overlap_cow": best["cow"],
                    "best_iou": best["iou"],
                }
            )
        timeline.append({**frame, "truth": truth})
    per_seed = {}
    for cow, rows in states.items():
        per_seed[cow] = {
            "emitted_seconds": len(rows),
            "first_unmatched": next(
                (row for row in rows if row["matched_cow"] is None), None
            ),
            "first_different_cow": next(
                (row for row in rows if row["matched_cow"] not in (None, cow)), None
            ),
            "all_matches": dict(Counter(str(row["matched_cow"]) for row in rows)),
            "scored_matches": dict(
                Counter(str(row["matched_cow"]) for row in rows if row["second"] >= 330)
            ),
        }
    return {
        "per_seed": per_seed,
        "scored_box_errors": assess(
            {"timeline": [row for row in timeline if row["second"] >= 330]}
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("propagation", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.propagation.read_text())
    if not value["complete"] or [row["second"] for row in value["timeline"]] != list(
        range(630)
    ):
        parser.error("This audit requires the complete frozen0–629 second panel")
    if digest(args.annotations) != value["provenance"]["annotations_sha256"]:
        parser.error("Annotation provenance differs from the evaluated cache")
    records, _ = annotations(args)
    report = {
        "scope": "Post-hoc development failure audit; no new model or tuning",
        "propagation_sha256": digest(args.propagation),
        "annotation_sha256": digest(args.annotations),
        "interpretation": "One-to-one box matching can alternate between duplicate slots; first different-cow assignment alone does not prove a physical track jump. Geometric categories are review hints, not mask labels.",
        **audit(value, records),
    }
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
