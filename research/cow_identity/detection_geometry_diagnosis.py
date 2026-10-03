"""Separate geometry loss from full-collection assignment interference."""

import json
from collections import Counter
from pathlib import Path

from benchmark import digest, write_json
from detection_errors import overlaps
from detection_output_geometry import (
    FILES,
    RESULTS,
    baseline_boxes,
    detector_boxes,
    load_inputs,
)
from video_assessment import pair_boxes, truth_at


def outcome(actual, named):
    if actual is None:
        return "unmatched_named"
    if actual not in range(1, 7):
        return "unknown_named"
    return "correct_name" if actual == named else "wrong_name"


def frame_diagnosis(frame, seeds, truth):
    before = baseline_boxes(frame, seeds)
    after = detector_boxes(frame, seeds)
    original_pairs, raw_pairs = pair_boxes(before, truth), pair_boxes(after, truth)
    slots = {box.track_id: index for index, box in enumerate(before)}
    partners = {
        row["track_id"]: row["proposal_index"] for row in frame["reciprocal_pairs"]
    }
    proposal_slots = {index: slot for slot, index in partners.items()}
    rows = []
    for slot in frame["named_track_ids"]:
        named, index, proposal = seeds[slot]["cow"], slots[slot], partners[slot]
        actual_before = (
            truth[original_pairs[index]]["cow"] if index in original_pairs else None
        )
        actual_after = (
            truth[raw_pairs[proposal]]["cow"] if proposal in raw_pairs else None
        )
        own_before = next(
            (row for row in overlaps(before[index], truth) if row["cow"] == named), None
        )
        own_after = next(
            (row for row in overlaps(after[proposal], truth) if row["cow"] == named),
            None,
        )
        winner = next(
            (i for i, target in raw_pairs.items() if truth[target]["cow"] == named),
            None,
        )
        original, corrected = (
            outcome(actual_before, named),
            outcome(actual_after, named),
        )
        cause = None
        if original == "correct_name" and corrected != "correct_name":
            cause = (
                "raw_box_below_own_iou_threshold"
                if own_after["iou"] < 0.5
                else "valid_raw_box_loses_global_assignment"
            )
        winner_kind = None
        if winner is not None and winner != proposal:
            winner_kind = (
                "unpaired_raw_proposal"
                if winner not in proposal_slots
                else "unnamed_reciprocal_proposal"
                if proposal_slots[winner] not in frame["named_track_ids"]
                else "other_named_reciprocal_proposal"
            )
        rows.append(
            {
                "second": frame["second"],
                "slot": slot,
                "name": named,
                "before": original,
                "after": corrected,
                "cause": cause,
                "original_own_overlap": own_before,
                "raw_own_overlap": own_after,
                "original_assigned_cow": actual_before,
                "raw_assigned_cow": actual_after,
                "proposal_index": proposal,
                "own_truth_winning_proposal": winner,
                "competing_proposal_kind": winner_kind,
            }
        )
    return rows


def summarize(rows):
    return {
        "named_observations": len(rows),
        "transitions": dict(
            Counter(f"{row['before']}->{row['after']}" for row in rows)
        ),
        "loss_causes": dict(Counter(row["cause"] for row in rows if row["cause"])),
        "assignment_loss_winners": dict(
            Counter(
                row["competing_proposal_kind"] or "own_truth_unmatched"
                for row in rows
                if row["cause"] == "valid_raw_box_loses_global_assignment"
            )
        ),
        "geometry_own_iou_decreased": sum(
            row["raw_own_overlap"] is not None
            and row["raw_own_overlap"]["iou"] < row["original_own_overlap"]["iou"]
            for row in rows
        ),
    }


def run():
    frozen, data, records = load_inputs()
    value, clip = data["streaming"], data["clip"]
    report_path = RESULTS / "cutie-output-geometry.json"
    results = json.loads(report_path.read_text())
    groups, details = {}, []
    for start, stop in frozen["windows"]:
        rows = []
        for frame in value["timeline"]:
            if start <= frame["second"] <= stop:
                truth = truth_at(
                    records, frame["publisher_frame"], clip["width"], clip["height"]
                )
                rows.extend(
                    frame_diagnosis(frame, value["provenance"]["seed_prompts"], truth)
                )
        for key, state in (
            ("recorded_mask_geometry", "before"),
            ("all_actual_detector_proposals", "after"),
        ):
            expected = results["conditions"][key][str(start)]["naming_counts"]
            if any(
                sum(row[state] == outcome for row in rows) != expected[outcome]
                for outcome in (
                    "correct_name",
                    "wrong_name",
                    "unknown_named",
                    "unmatched_named",
                )
            ):
                raise ValueError("Diagnostic outcomes differ from the saved comparison")
        groups[str(start)] = summarize(rows)
        details.extend(rows)
    report = {
        "scope": "Post-result diagnosis across all named observations in all five exposed panels; no alternative policy is scored or selected",
        "source_report_sha256": digest(report_path),
        "source_streaming_sha256": digest(FILES["streaming"]),
        "runner_sha256": digest(Path(__file__)),
        "panels": groups,
        "all_panels": summarize(details),
        "changed_outcomes": [row for row in details if row["before"] != row["after"]],
        "strict_outcome_parity": True,
    }
    write_json(RESULTS / "cutie-output-geometry-diagnosis.json", report)
    print(json.dumps(report["all_panels"]))


if __name__ == "__main__":
    run()
