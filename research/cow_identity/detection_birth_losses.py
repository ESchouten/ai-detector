"""Posthoc attribution of fixed crowded-birth coverage; no new inference/tuning."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_birth_run import PROTOCOL, checked_inputs
from detection_streaming_assessment import WINDOWS
from video_assessment import annotations, pair_boxes, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
RUNS = {
    "eight_initial_slots": Path(
        ".cache/cow-cutie/streaming-development/streaming.json"
    ),
    "six_plus_births": Path(".cache/cow-cutie/crowded-births/streaming.json"),
}
REPORTS = {
    "eight_initial_slots": ROOT
    / "results/2026-10-03/detection/cutie-streaming-development.json",
    "six_plus_births": ROOT / "results/2026-10-03/detection/crowded-births.json",
}


def slot_gates(frame, track):
    objects = {row["track_id"]: row for row in frame["objects"]}
    gates = []
    if objects.get(track, {}).get("p10_probability", 0) < 0.7:
        gates.append("low_p10")
    if track not in {row["track_id"] for row in frame["reciprocal_pairs"]}:
        gates.append("no_reciprocal_detector")
    if track + 1 in frame["conflicted_ids"]:
        gates.append("quarantined")
    return gates


def frame_outcomes(frame, truth):
    boxes = [BoundingBox(**row) for row in frame["boxes"]]
    pairs = pair_boxes(boxes, truth)
    matched = {truth[j]["cow"]: boxes[i] for i, j in pairs.items()}
    output = {}
    for row in truth:
        cow = row["cow"]
        if cow > 6:
            continue
        box = matched.get(cow)
        if box is None:
            reasons = ["no_localization_match"]
        elif box.track_id != cow - 1:
            reasons = ["matched_different_slot"]
        else:
            reasons = slot_gates(frame, box.track_id)
        correct = bool(
            box and box.track_id == cow - 1 and box.track_id in frame["named_track_ids"]
        )
        if correct != (not reasons):
            raise ValueError("Attribution must reproduce the frozen naming policy")
        output[cow] = {
            "second": frame["second"],
            "cow": cow,
            "correct": correct,
            "matched_track": box.track_id if box else None,
            "reasons": reasons,
        }
    return output


def summarize_rows(rows):
    counts = Counter(
        "correct" if r["correct"] else "+".join(r["reasons"]) for r in rows
    )
    gates = Counter(reason for row in rows for reason in row["reasons"])
    return {
        "visible_known": len(rows),
        "correct": counts["correct"],
        "coverage": counts["correct"] / len(rows) if rows else 0,
        "exclusive_reasons": dict(counts),
        "overlapping_gate_counts": dict(gates),
    }


def evaluate(value, records, clip, official):
    panels, outcomes = {}, {}
    for start, stop in WINDOWS:
        per_cow = defaultdict(list)
        for frame in value["timeline"][start : stop + 1]:
            truth = truth_at(
                records,
                round(frame["second"] * clip["source_fps"]) + 1,
                clip["width"],
                clip["height"],
            )
            for cow, row in frame_outcomes(frame, truth).items():
                per_cow[cow].append(row)
                outcomes[(frame["second"], cow)] = row
        all_rows = [r for rows in per_cow.values() for r in rows]
        panel = {
            "all": summarize_rows(all_rows),
            "per_cow": {str(c): summarize_rows(rows) for c, rows in per_cow.items()},
        }
        expected = official["conditions"][str(start)]["naming_counts"]
        if (
            panel["all"]["visible_known"] != expected["visible_known"]
            or panel["all"]["correct"] != expected["correct_name"]
        ):
            raise ValueError("Per-cow attribution differs from original strict totals")
        panels[str(start)] = panel
    return panels, outcomes


def compare(outcomes):
    before, after = (outcomes[key] for key in RUNS)
    if before.keys() != after.keys():
        raise ValueError("Different visible truth observations in baseline and control")
    result = {}
    for start, stop in WINDOWS:
        per_cow = {}
        for cow in range(1, 7):
            keys = [k for k in before if start <= k[0] <= stop and k[1] == cow]
            lost = [
                after[k]
                for k in keys
                if before[k]["correct"] and not after[k]["correct"]
            ]
            gained = [
                before[k]
                for k in keys
                if not before[k]["correct"] and after[k]["correct"]
            ]
            per_cow[str(cow)] = {
                "lost": summarize_rows(lost),
                "gained": summarize_rows(gained),
                "net_correct_change": len(gained) - len(lost),
            }
        result[str(start)] = per_cow
    return result


def execute():
    protocol, clip, _, _ = checked_inputs(PROTOCOL)
    annotation_paths = [
        Path(p) for p in protocol["files"] if p.endswith((".safe-v1.npz", ".pkl"))
    ]
    args = SimpleNamespace(
        annotations=next(p for p in annotation_paths if p.suffix == ".npz"),
        source_pickle=next(p for p in annotation_paths if p.suffix == ".pkl"),
    )
    records, _ = annotations(args)
    panels, outcomes = {}, {}
    for name, path in RUNS.items():
        value, official = (
            json.loads(path.read_text()),
            json.loads(REPORTS[name].read_text()),
        )
        expected = official.get(
            "streaming_sha256", official.get("sources", {}).get(str(path))
        )
        if digest(path) != expected or not value["complete"]:
            raise ValueError(
                "Only completed, unchanged officially scored runs are allowed"
            )
        panels[name], outcomes[name] = evaluate(value, records, clip, official)
    report = {
        "scope": "Posthoc CPU explanation only; exact original one-to-one IoU .5 assignments, all known truth observations, fixed naming gates, no threshold selection",
        "reason_semantics": "no_localization_match means no propagated LCC box received the truth match, not necessarily a raw YOLO miss. matched_different_slot is a geometrically matched box with no corresponding original name. Low-p10/reciprocal/quarantine counts overlap; exclusive combinations partition observations.",
        "sources": {
            str(p): digest(p)
            for p in [
                *RUNS.values(),
                *REPORTS.values(),
                *annotation_paths,
                PROTOCOL,
                Path(__file__),
                ROOT / "video_assessment.py",
            ]
        },
        "panels": panels,
        "changes_vs_eight_initial_slots": compare(outcomes),
    }
    write_json(ROOT / "results/2026-10-03/detection/birth-coverage-losses.json", report)
    print(
        json.dumps(
            {"panels": panels, "changes": report["changes_vs_eight_initial_slots"]}
        )
    )


if __name__ == "__main__":
    execute()
