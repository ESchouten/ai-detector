"""Posthoc observable absence inventory; no intervention, tuning or model calls."""

import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json

ROOT = Path(__file__).parent
OUTPUT = ROOT / "results/2026-10-03/detection/departure-inventory.json"
CROWD = Path(".cache/cow-cutie/crowded-births/streaming.json")
PASSAGE = Path(".cache/cow-passage-entry-births/predictions.json")
ANNOTATIONS = Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz")
PASSAGE_TRUTH = ROOT / "results/2026-10-03/purdue-entry-annotations.json"


def absent_runs(rows, field, threshold=5.0):
    """Measured spans start at the first absent sample, not the last positive."""
    runs, current = [], []
    for row in rows:
        if current and row["second"] - current[-1]["second"] != 0.5:
            runs.append(current)
            current = []
        if row[field]:
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    output = []
    for run in runs:
        start, end = run[0]["second"], run[-1]["second"]
        output.append(
            {
                "start": start,
                "end": end,
                "observed_span_seconds": end - start,
                "samples": len(run),
                "right_censored": end == rows[-1]["second"],
                "five_second_trigger": start + threshold
                if end - start >= threshold
                else None,
                "annotation_context": dict(Counter(r["truth"] for r in run)),
            }
        )
    return output


def checked_mask(frame, path):
    if digest(path) != frame["mask_sha256"]:
        raise ValueError(f"Changed recorded mask: {path}")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if mask is None or mask.ndim != 2:
        raise ValueError("Indexed mask required")
    counts = np.bincount(mask.ravel())
    live = {int(i) for i in frame["object_to_channel"]}
    if not set(np.flatnonzero(counts)).issubset({0, *live}):
        raise ValueError("Undeclared object pixels")
    return {i: int(counts[i]) if i < len(counts) else 0 for i in live}


def crowd_truth():
    # Read only frame/identity metadata and immediately retain the exposed
    # 0–1529s rows. No coordinates, reserved images or later IDs are analyzed.
    with np.load(ANNOTATIONS, allow_pickle=False) as archive:
        frames = archive["frame_id"]
        selected = (frames >= 1) & (frames <= 1529 * 20 + 1)
        frames, cows = frames[selected], archive["cow_id"][selected]
    lookup = {}
    for frame, cow in zip(frames, cows, strict=True):
        lookup.setdefault(int(frame), set()).add(int(cow))
    return lookup


def describe(rows):
    absent = absent_runs(rows, "no_foreground")
    uncorroborated = absent_runs(rows, "no_reciprocal")
    triggers = [r for r in absent if r["five_second_trigger"] is not None]
    return {
        "active_from": rows[0]["second"],
        "active_until": rows[-1]["second"],
        "samples": len(rows),
        "minimum_foreground_pixels": min(r["pixels"] for r in rows),
        "zero_foreground_samples": sum(r["no_foreground"] for r in rows),
        "no_reciprocal_samples": sum(r["no_reciprocal"] for r in rows),
        "zero_foreground_runs": absent,
        "no_reciprocal_runs": uncorroborated,
        "max_zero_foreground_span": max(
            (r["observed_span_seconds"] for r in absent), default=0
        ),
        "max_no_reciprocal_span": max(
            (r["observed_span_seconds"] for r in uncorroborated), default=0
        ),
        "first_potential_retirement": triggers[0] if triggers else None,
    }


def examine(path, truth, *, crowded):
    value = json.loads(path.read_text())
    frames = value["all_frames"] if crowded else value["timeline"]
    expected_length = 3059 if crowded else 22
    if not value["complete"] or [r["second"] for r in frames] != [
        i / 2 for i in range(expected_length)
    ]:
        raise ValueError("Complete original exposed chronology required")
    objects, scene_rows = {}, []
    for index, frame in enumerate(frames):
        stem = f"{frame['second']:g}" if crowded else f"{index:03d}"
        counts = checked_mask(frame, path.parent / "masks" / f"{stem}.png")
        reciprocal = {p["track_id"] + 1 for p in frame["reciprocal_pairs"]}
        visible = (
            truth[frame["publisher_frame"]]
            if crowded
            else {b["cow"] for b in truth[index]["boxes"]}
        )
        for object_id, pixels in sorted(counts.items()):
            # Anonymous stable IDs7/8 (or2 in the passage) are never equated
            # with publisher identities. Only the reviewed seed names map.
            cow = object_id if crowded and object_id <= 6 else None
            if not crowded and object_id == 1:
                cow = 5676
            context = (
                "anonymous_no_biological_mapping"
                if cow is None
                else "seed_animal_annotated"
                if cow in visible
                else "seed_animal_not_annotated"
            )
            objects.setdefault(object_id, []).append(
                {
                    "second": frame["second"],
                    "pixels": pixels,
                    "no_foreground": pixels == 0,
                    "no_reciprocal": object_id not in reciprocal,
                    "truth": context,
                }
            )
        scene_rows.append(
            {
                "second": frame["second"],
                "truth_visible_count": len(visible),
                "foreground_pixels": sum(counts.values()),
                "per_object_pixels": counts,
                "reciprocal_ids": sorted(reciprocal),
            }
        )
        if index % 500 == 0:
            print(f"{path.parent.name}: {index + 1}/{len(frames)}", flush=True)
    return {
        "objects": {str(i): describe(rows) for i, rows in objects.items()},
        "empty_annotated_scene_rows": [
            row for row in scene_rows if row["truth_visible_count"] == 0
        ],
        "scene_rows": scene_rows if not crowded else None,
        "evidence": {
            "processed_rows": len(frames),
            "validated_indexed_masks": len(frames),
            "first_second": frames[0]["second"],
            "last_second": frames[-1]["second"],
        },
    }


def run():
    if OUTPUT.exists():
        raise ValueError("Preserve any existing diagnostic")
    sources = [
        CROWD,
        PASSAGE,
        ANNOTATIONS,
        PASSAGE_TRUTH,
        Path(__file__),
        ROOT / "detection_birth_protocol.json",
        ROOT / "passage_entry_birth_protocol.json",
        ROOT / "results/2026-10-03/detection/crowded-births.json",
        ROOT / "results/2026-10-03/purdue-entry-births.json",
    ]
    # Bind to the already scored executions; do not substitute candidate runs.
    for path, report_path in zip((CROWD, PASSAGE), sources[-2:], strict=True):
        report = json.loads(report_path.read_text())
        if report["sources"][str(path)] != digest(path):
            raise ValueError("The completed scored baseline changed")
    passage_truth = json.loads(PASSAGE_TRUTH.read_text())["frames"]
    report = {
        "scope": "CPU factual inventory of completed births-only outputs, not a retirement intervention or alternative accuracy score.",
        "sources": {str(p): digest(p) for p in sources},
        "rule_examined": "Potential retirement after5.0s from the first zero-foreground sample, requiring11 consecutive2Hz observations. Any foreground pixel resets. No-frame/gapped periods are not absence evidence. No thresholds are searched.",
        "annotation_limit": "Crowd annotations have no occlusion/absence flag and contain omissions. An annotated seed is evidence against calling a detector miss a departure; an omitted label alone does not prove departure. Anonymous slotIDs do not identify animals. Passage labels retain uncertain fragments and five empty frames.",
        "crowded": examine(CROWD, crowd_truth(), crowded=True),
        "passage": examine(PASSAGE, passage_truth, crowded=False),
        "counterfactual_limit": "Potential triggers are read from an unchanged cached trajectory. Actually removing a slot changes later competition, so this does not predict post-retirement masks or safe re-entry.",
    }
    write_json(OUTPUT, report)
    print(digest(OUTPUT))


if __name__ == "__main__":
    run()
