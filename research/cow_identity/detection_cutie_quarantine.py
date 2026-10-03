"""Replay a frozen, label-free collision quarantine over cached indexed masks."""

import argparse
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components, probability_gate, verified_mask
from detection_sam_tracking import score
from video_assessment import annotations


@dataclass
class PastFrame:
    second: int
    mask: np.ndarray
    areas: dict
    probabilities: dict
    conflicted: set


@dataclass
class Conflict:
    donor: int
    receiver: int
    reference_area: float
    anchor: np.ndarray
    restored_frames: int = 0


class CollisionQuarantine:
    """Suppress names after ownership transfer; never change an object's pixels."""

    def __init__(self, rules, object_ids):
        self.rules = rules
        self.object_ids = tuple(object_ids)
        self.history = deque(maxlen=rules["history_frames"])
        self.conflicts = {}
        self.events = []

    @staticmethod
    def anchor_fraction(mask, object_id, anchor):
        return float(np.count_nonzero((mask == object_id) & anchor) / anchor.sum())

    def restore(self, second, mask, areas):
        for pair, conflict in list(self.conflicts.items()):
            restored = (
                areas[conflict.donor]
                >= self.rules["recovery_donor_area_ratio"] * conflict.reference_area
                and self.anchor_fraction(mask, conflict.donor, conflict.anchor)
                >= self.rules["recovery_donor_anchor_fraction"]
                and self.anchor_fraction(mask, conflict.receiver, conflict.anchor)
                <= self.rules["recovery_receiver_anchor_fraction"]
            )
            conflict.restored_frames = conflict.restored_frames + 1 if restored else 0
            if conflict.restored_frames >= self.rules["recovery_frames"]:
                del self.conflicts[pair]
                self.events.append(
                    {"second": second, "kind": "restored", "pair": list(pair)}
                )

    def anchor_for(self, donor, reference_area):
        candidates = [
            frame
            for frame in self.history
            if donor not in frame.conflicted
            and frame.probabilities.get(donor, 0)
            >= self.rules["anchor_minimum_probability"]
            and frame.areas[donor]
            >= self.rules["anchor_minimum_area_ratio"] * reference_area
        ]
        return max(
            candidates,
            key=lambda frame: (frame.probabilities[donor], frame.second),
            default=None,
        )

    def discover(self, second, mask, areas):
        if len(self.history) < self.rules["history_frames"]:
            return
        for donor in self.object_ids:
            reference = float(np.median([frame.areas[donor] for frame in self.history]))
            if (
                reference <= 0
                or areas[donor] >= self.rules["collapse_ratio"] * reference
            ):
                continue
            anchor_frame = self.anchor_for(donor, reference)
            if anchor_frame is None:
                continue
            anchor = anchor_frame.mask == donor
            for receiver in self.object_ids:
                pair = (donor, receiver)
                if receiver == donor or pair in self.conflicts:
                    continue
                fraction = self.anchor_fraction(mask, receiver, anchor)
                if fraction < self.rules["receiver_anchor_fraction"]:
                    continue
                self.conflicts[pair] = Conflict(donor, receiver, reference, anchor)
                self.events.append(
                    {
                        "second": second,
                        "kind": "quarantined",
                        "pair": list(pair),
                        "donor_area": areas[donor],
                        "reference_area": reference,
                        "anchor_second": anchor_frame.second,
                        "anchor_probability": anchor_frame.probabilities[donor],
                        "receiver_anchor_fraction": fraction,
                    }
                )

    def observe(self, second, mask, probabilities):
        if self.history and second != self.history[-1].second + 1:
            raise ValueError("Quarantine requires consecutive integer-second masks")
        areas = {
            object_id: int(np.count_nonzero(mask == object_id))
            for object_id in self.object_ids
        }
        self.restore(second, mask, areas)
        self.discover(second, mask, areas)
        conflicted = {object_id for pair in self.conflicts for object_id in pair}
        self.history.append(
            PastFrame(second, mask.copy(), areas, probabilities.copy(), conflicted)
        )
        return conflicted


def replay(value, directory, clip, rules, object_ids):
    tracker = CollisionQuarantine(rules, object_ids)
    timeline, conflicts = [], {}
    for frame in value["timeline"]:
        mask = verified_mask(
            directory, frame, (clip["height"], clip["width"]), len(object_ids)
        )
        probabilities = {
            item["track_id"] + 1: item["p10_probability"] for item in frame["objects"]
        }
        conflicts[frame["second"]] = sorted(
            tracker.observe(frame["second"], mask, probabilities)
        )
        cleaned, _ = largest_components(mask)
        timeline.append({**frame, "boxes": boxes_from_mask(cleaned)})
    return {**value, "timeline": timeline}, conflicts, tracker.events


def compare(value, records, clip, source_protocol, rules, conflicts):
    quality = probability_gate(rules["base"]["minimum_p10_probability"])

    def allowed(frame, box):
        return (
            quality(frame, box) and box.track_id + 1 not in conflicts[frame["second"]]
        )

    results = {}
    for name, window in rules["score_windows"].items():
        protocol = {**source_protocol, "score_seconds": window}
        results[name] = {
            label: score(
                value,
                records,
                clip,
                protocol,
                value["provenance"]["seed_prompts"],
                name_allowed=gate,
            )
            for label, gate in (("base", quality), ("quarantine", allowed))
        }
    return results


def load_inputs(args):
    value = json.loads(args.propagation.read_text())
    source_protocol = json.loads(args.source_protocol.read_text())
    rules = json.loads(args.protocol.read_text())
    clip = json.loads(args.sampled_manifest.read_text())
    if (
        not value["complete"]
        or digest(args.propagation) != rules["propagation_sha256"]
        or digest(args.source_protocol) != rules["source_protocol_sha256"]
        or value["provenance"]["protocol_sha256"] != rules["source_protocol_sha256"]
        or digest(args.sampled_manifest) != source_protocol["sampled_manifest_sha256"]
        or clip["contract"]["video_sha256"] != source_protocol["video_sha256"]
        or digest(args.source_pickle) != source_protocol["source_annotations_sha256"]
    ):
        raise ValueError("Incomplete propagation or changed frozen source provenance")
    if [row["second"] for row in value["timeline"]] != list(
        range(rules["processed_seconds"][0], rules["processed_seconds"][1] + 1)
    ):
        raise ValueError("Replay requires every frozen integer-second mask")
    return value, source_protocol, rules, clip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "source-protocol",
        "protocol",
        "sampled-manifest",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    value, source_protocol, rules, clip = load_inputs(args)
    records, _ = annotations(args)
    transformed, conflicts, events = replay(
        value,
        args.propagation.parent,
        clip,
        rules,
        range(1, len(source_protocol["seeded_cows"]) + 1),
    )
    results = compare(transformed, records, clip, source_protocol, rules, conflicts)
    report = {
        "scope": rules["scope"],
        "protocol_sha256": digest(args.protocol),
        "propagation_sha256": digest(args.propagation),
        "annotations_sha256": digest(args.annotations),
        "runner_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "conditions": results,
        "events": events,
        "conflicted_ids_by_second": conflicts,
    }
    write_json(args.output, report)
    print(json.dumps({"conditions": results, "events": events}))


if __name__ == "__main__":
    main()
