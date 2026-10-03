"""Fixed control: expand original slots to include reciprocal detector extents."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from benchmark import digest, write_json
from detection_output_geometry import (
    FILES,
    RESULTS,
    ROOT,
    baseline_boxes,
    load_inputs,
    measure,
)
from detection_reserved_score import acceptance

PROTOCOL = ROOT / "detection_union_geometry_protocol.json"


def union_boxes(frame, seeds):
    """Retain every original slot/name; union any reciprocal pair without shrinking."""
    boxes = baseline_boxes(frame, seeds)
    partners = {
        row["track_id"]: row["proposal_index"] for row in frame["reciprocal_pairs"]
    }
    if len(partners) != len(frame["reciprocal_pairs"]) or len(
        set(partners.values())
    ) != len(partners):
        raise ValueError("Union geometry requires unique original reciprocal pairs")
    result = []
    for box in boxes:
        if box.track_id in partners:
            proposal = frame["raw_detector_boxes"][partners[box.track_id]]
            box = replace(
                box,
                x1=min(box.x1, proposal["x1"]),
                y1=min(box.y1, proposal["y1"]),
                x2=max(box.x2, proposal["x2"]),
                y2=max(box.y2, proposal["y2"]),
            )
        result.append(box)
    return result


def freeze():
    if PROTOCOL.exists():
        raise ValueError("Preserve the frozen union control")
    previous = ROOT / "detection_output_geometry_protocol.json"
    report = RESULTS / "cutie-output-geometry.json"
    diagnosis = RESULTS / "cutie-output-geometry-diagnosis.json"
    paths = [
        Path(__file__),
        ROOT / "test_detection_union_geometry.py",
        previous,
        report,
        diagnosis,
    ]
    inherited = json.loads(previous.read_text())
    write_json(
        PROTOCOL,
        {
            "scope": "Single geometry hypothesis on all five exposed panels; not a rescued reserved evaluation. Seconds 3000 onward remain closed.",
            "windows": inherited["windows"],
            "conditions": ["recorded_mask_geometry", "reciprocal_union_original_slots"],
            "policy": "Keep original slot collection, order, confidence, named decisions, gates and reciprocal pairs unchanged. For EVERY reciprocal slot (named or unnamed), take the coordinate union of original largest-component box and its current raw detector box. Slots without a reciprocal partner retain original geometry. No new boxes, removed boxes, assigned names, thresholds, smoothing or selection.",
            "rationale": "The preceding all-raw output loses 215 correct names: 133 from worse own-cow geometry and 82 from global assignment interference (81 extra unpaired proposals). Union cannot shrink the original extent and retaining slots avoids introducing these extra proposals. Enlargement may still add background/neighbor area or alter global matching, so this is a falsifiable control.",
            "evaluation": "Use unchanged full-truth one-to-one IoU>=.5 VideoMetrics on all five panels. Demand exact original baseline counts/confusions, retain every wrong-known, unknown-named, unmatched-named, miss and duplicate. Names/box counts must stay identical. No operating-point sweep.",
            "acceptance": inherited["acceptance"],
            "files": {str(path): digest(path) for path in paths},
            "inherited_inputs": "All source/implementation/library bindings from detection_output_geometry_protocol.json are also checked",
            "inference": "None; reuse completed recorded outputs only",
        },
    )


def run():
    frozen = json.loads(PROTOCOL.read_text())
    for path, expected in frozen["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen union input changed: {path}")
    inherited, data, records = load_inputs()
    if frozen["windows"] != inherited["windows"]:
        raise ValueError("Union windows differ from the five exposed panels")
    conditions = {
        name: measure(
            data["streaming"], records, data["clip"], frozen["windows"], transform
        )
        for name, transform in (
            ("recorded_mask_geometry", baseline_boxes),
            ("reciprocal_union_original_slots", union_boxes),
        )
    }
    original = json.loads((RESULTS / "cutie-output-geometry.json").read_text())[
        "conditions"
    ]["recorded_mask_geometry"]
    if conditions["recorded_mask_geometry"] != original:
        raise ValueError("Union replay must reproduce every saved baseline count")
    for key, changed in conditions["reciprocal_union_original_slots"].items():
        old = original[key]["naming_counts"]
        new = changed["naming_counts"]
        named = ("correct_name", "wrong_name", "unknown_named", "unmatched_named")
        if new["detector_boxes"] != old["detector_boxes"] or sum(
            new[name] for name in named
        ) != sum(old[name] for name in named):
            raise ValueError("Union changed the output collection or emitted names")
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(PROTOCOL),
        "streaming_sha256": digest(FILES["streaming"]),
        "conditions": conditions,
        "acceptance": {
            name: {
                panel: acceptance(result, frozen["acceptance"])
                for panel, result in rows.items()
            }
            for name, rows in conditions.items()
        },
        "baseline_exactly_reproduced": True,
        "same_emitted_names_and_box_counts": True,
        "no_reserved_claim": True,
    }
    write_json(RESULTS / "cutie-union-geometry.json", report)
    print(json.dumps(report["acceptance"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    args = parser.parse_args()
    freeze() if args.action == "freeze" else run()
