"""Audit a fixed early pseudo-label pool; labels never choose or repair its rows."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from recognition_masked_pilot import eligible
from recognition_temporal_inventory import OUTPUT as INVENTORY
from recognition_temporal_inventory import ROOT, TEACHER
from video_assessment import annotations, pair_boxes, truth_at

from aidetector.domain.models import BoundingBox


def execute():
    output = ROOT / "results/2026-10-03/recognition/temporal-teacher-audit.json"
    if output.exists():
        raise FileExistsError("Preserve completed teacher audit")
    inventory = json.loads(INVENTORY.read_text())
    if digest(TEACHER) != inventory["files"][str(TEACHER)]:
        raise ValueError("Teacher changed since early inventory")
    data = json.loads(TEACHER.read_text())
    frames = [frame for frame in data["timeline"] if 0 <= frame["second"] <= 629]
    selected = {}
    for frame in frames:
        stats = {row["track_id"]: row for row in frame["objects"]}
        selected[frame["second"]] = [
            i for i, box in enumerate(frame["boxes"]) if eligible(frame, box, stats)
        ]
    # Fixed pool complete before truth is opened; no per-row training exclusion follows.
    paths = SimpleNamespace(
        annotations=Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
        source_pickle=Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
    )
    records, _ = annotations(paths)
    counts, examples = defaultdict(Counter), []
    for frame in frames:
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        truth = truth_at(records, frame["publisher_frame"], 800, 600)
        pairs = pair_boxes(boxes, truth)
        for index in selected[frame["second"]]:
            cow = boxes[index].track_id + 1
            assigned = truth[pairs[index]]["cow"] if index in pairs else None
            category = (
                "same_known_label"
                if assigned == cow
                else "unmatched_geometry"
                if assigned is None
                else "different_known_label"
                if assigned <= 6
                else "unknown_animal_label"
            )
            counts[cow][category] += 1
            if category != "same_known_label":
                examples.append(
                    {
                        "second": frame["second"],
                        "suggested_cow": cow,
                        "matched_publisher_cow": assigned,
                        "category": category,
                    }
                )
    total = sum(counts.values(), Counter())
    write_json(
        output,
        {
            "scope": "Teacher contamination diagnostic on fixed0..629 candidate pool only, not training, calibration or query scoring. Original labels/selection unchanged.",
            "files": {
                str(path): digest(path)
                for path in (
                    Path(__file__),
                    INVENTORY,
                    TEACHER,
                    paths.annotations,
                    paths.source_pickle,
                )
            },
            "pool_size": sum(total.values()),
            "counts": dict(total),
            "per_original_known_slot": {
                str(cow): dict(counter) for cow, counter in counts.items()
            },
            "all_disagreements": examples,
            "matching": "Original all-slot/all-eight maximum-cardinality thenIoU.5 matching, without names; count only preselected teacher candidates afterward.",
            "limits": "Publisher rectangle mismatch is not proof of a biological pseudo-label error; a correct rectangle match does not certify a clean single-animal foreground. No disagreements removed, IDs repaired, thresholds fitted or unknown7/8 examples added to training.",
        },
    )
    print(
        json.dumps(
            {
                "total": dict(total),
                "per_cow": {str(c): dict(n) for c, n in counts.items()},
            }
        )
    )


if __name__ == "__main__":
    execute()
