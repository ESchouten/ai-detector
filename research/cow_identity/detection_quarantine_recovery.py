"""Test current detector corroboration as recovery evidence for a conflicted pair."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_actual_audit import lcc_timeline
from detection_actual_score import load_inputs
from detection_box_consensus import correspondences
from detection_corroboration import measure
from detection_cutie_quarantine import CollisionQuarantine
from detection_cutie_variants import verified_mask
from video_assessment import annotations


class CorroboratedRecovery(CollisionQuarantine):
    """Keep original conflict discovery; use distinct current objects for recovery."""

    def __init__(self, rules, object_ids, recovery):
        super().__init__(rules, object_ids)
        self.recovery = recovery
        self.confirmations = {}
        self.probabilities = {}

    def observe_evidence(self, second, mask, probabilities, boxes, proposals):
        _, reciprocal = correspondences(boxes, proposals, self.recovery["minimum_iou"])
        self.confirmations = {
            boxes[index]["track_id"] + 1: proposal
            for index, proposal in reciprocal.items()
        }
        self.probabilities = probabilities
        return self.observe(second, mask, probabilities)

    def restore(self, second, mask, areas):
        for pair, conflict in list(self.conflicts.items()):
            donor, receiver = pair
            restored = (
                donor in self.confirmations
                and receiver in self.confirmations
                and self.confirmations[donor] != self.confirmations[receiver]
                and self.probabilities.get(donor, 0) >= self.recovery["minimum_p10"]
                and self.probabilities.get(receiver, 0) >= self.recovery["minimum_p10"]
                and areas[donor]
                >= self.recovery["donor_area_ratio"] * conflict.reference_area
            )
            conflict.restored_frames = conflict.restored_frames + 1 if restored else 0
            if conflict.restored_frames >= self.recovery["consecutive_frames"]:
                del self.conflicts[pair]
                self.events.append(
                    {"second": second, "kind": "restored", "pair": list(pair)}
                )


def replay_recovery(directory, original_rows, value, detections, clip, rules, recovery):
    detector_boxes = {
        frame["second"]: frame["boxes"] for frame in detections["timeline"]
    }
    tracker = CorroboratedRecovery(rules, range(1, 9), recovery)
    conflicts = {}
    for frame in value["timeline"]:
        # Cache contains LCC geometry, while discovery uses unmodified indexed masks.
        original = {**frame, "boxes": original_rows[frame["second"]]["boxes"]}
        mask = verified_mask(directory, original, (clip["height"], clip["width"]), 8)
        probabilities = {
            row["track_id"] + 1: row["p10_probability"] for row in frame["objects"]
        }
        conflicts[str(frame["second"])] = sorted(
            tracker.observe_evidence(
                frame["second"],
                mask,
                probabilities,
                frame["boxes"],
                detector_boxes[frame["second"]],
            )
        )
    return conflicts, tracker.events


def execute(args):
    frozen = json.loads(args.recovery_protocol.read_text())
    for path, expected in frozen["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Changed frozen recovery input: {path}")
    protocol, rules, original, detections, clip = load_inputs(args)
    value = lcc_timeline(original, args.propagation.parent, clip)
    original_rows = {frame["second"]: frame for frame in original["timeline"]}
    conflicts, events = replay_recovery(
        args.propagation.parent,
        original_rows,
        value,
        detections,
        clip,
        rules,
        frozen["recovery"],
    )
    baseline = json.loads(args.baseline_report.read_text())
    overlaps = {
        int(second): {int(slot): overlap for slot, overlap in row.items()}
        for second, row in baseline["maximum_iou_by_second_and_original_slot"].items()
    }
    records, _ = annotations(args)
    conditions = {}
    for name, current in (
        ("original_quarantine", baseline["conflicted_ids_by_second"]),
        ("corroborated_recovery", conflicts),
    ):
        conditions[name] = {
            str(window[0]): measure(
                value,
                records,
                clip,
                protocol,
                {"minimum_p10_probability": rules["base"]["minimum_p10_probability"]},
                {"conflicted_ids_by_second": current},
                overlaps,
                window,
                protocol["corroborator"]["minimum_iou"],
            )
            for window in protocol["comparison_windows"]
        }
    if any(
        conditions["original_quarantine"][window] != row["frozen_pipeline"]
        for window, row in baseline["conditions"].items()
    ):
        raise ValueError(
            "Recovery control must exactly reproduce the original condition"
        )
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.recovery_protocol),
        "conditions": conditions,
        "events": events,
        "conflicted_ids_by_second": conflicts,
        "baseline_exactly_reproduced": True,
        "limitation": "Distinct current geometry is not proof that original names stayed with the same animals.",
    }
    write_json(args.output, report)
    print(json.dumps({"conditions": conditions, "events": events}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "protocol",
        "quarantine-protocol",
        "corroborator",
        "sampled-manifest",
        "seed-manifest",
        "annotations",
        "source-pickle",
        "baseline-report",
        "recovery-protocol",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    execute(parser.parse_args())
