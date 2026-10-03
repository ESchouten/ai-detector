"""One fixed control: actual reciprocal detector bounds, original slot collection."""

import argparse
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_birth_extended import checked_inputs, validate_frames
from detection_reserved_score import acceptance
from detection_sam_tracking import score
from video_assessment import annotations

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/detection"
PROTOCOL = ROOT / "detection_reciprocal_geometry_protocol.json"
BOUNDS = ("x1", "y1", "x2", "y2")
WINDOWS = ((330, 629), (930, 1229), (1230, 1529), (1800, 2099), (2700, 2999))
INPUTS = {
    "execution": ROOT / "detection_birth_extended_protocol.json",
    "streaming": Path(".cache/cow-cutie/crowded-joint-extended/streaming.json"),
    "development": RESULTS / "crowded-joint-readout.json",
    "extension": RESULTS / "crowded-joint-extended.json",
    "audit": RESULTS / "crowded-joint-extended-independent-audit.json",
    "annotations": Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    "source_pickle": Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
}


def substitute_frame(frame):
    """No truth, selection, extra outputs or temporal decision changes."""
    pairs = frame["reciprocal_pairs"]
    mapping = {pair["track_id"]: pair["proposal_index"] for pair in pairs}
    ids = [box["track_id"] for box in frame["boxes"]]
    if (
        len(ids) != len(set(ids))
        or len(mapping) != len(pairs)
        or len(set(mapping.values())) != len(mapping)
        or not set(mapping).issubset(ids)
        or not set(frame["named_track_ids"]).issubset(mapping)
        or any(
            not 0 <= index < len(frame["raw_detector_boxes"])
            for index in mapping.values()
        )
    ):
        raise ValueError("Require unique recorded reciprocal partners for every name")
    boxes = []
    for box in frame["boxes"]:
        replacement = box.copy()
        if box["track_id"] in mapping:
            proposal = frame["raw_detector_boxes"][mapping[box["track_id"]]]
            replacement.update({key: proposal[key] for key in (*BOUNDS, "confidence")})
        boxes.append(replacement)
    return {**frame, "boxes": boxes}


def freeze():
    if PROTOCOL.exists():
        raise FileExistsError("Preserve frozen reciprocal comparison")
    helpers = [
        Path(__file__),
        ROOT / "test_detection_reciprocal_geometry.py",
        ROOT / "ANNOTATION_TEMPORAL_GEOMETRY.md",
        ROOT / "annotation_temporal_geometry.py",
        RESULTS / "annotation-temporal-geometry.json",
        ROOT / "detection_output_geometry.py",
        ROOT / "detection_union_geometry.py",
        RESULTS / "cutie-output-geometry.json",
        RESULTS / "cutie-union-geometry.json",
    ]
    write_json(
        PROTOCOL,
        {
            "scope": "One fixed CPU output-geometry comparison on all five exposed panels; no new video/model access, no parameter search, original failure retained. Source seconds >=3000 remain closed.",
            "windows": [list(window) for window in WINDOWS],
            "conditions": [
                "recorded_mask_slots",
                "reciprocal_detector_bounds_same_slots",
            ],
            "policy": "Keep every original slot, order, label, track ID, name and temporal decision verbatim. For every unique recorded reciprocal pair, named or unnamed, replace only x1/y1/x2/y2 and confidence with its existing same-frame raw detector proposal. Unpaired slots remain unchanged; unpaired proposals never appear. The frozen detector has only class0 cow, so original cow labels stay unchanged. No averaging, padding, clipping, filtering, new association or threshold.",
            "order": "Transform every scored timeline row before opening annotation arrays, then score both conditions with the same original scorer and all-eight truth. Exact baseline counts/confusions required on each panel.",
            "acceptance": {
                "minimum_conservative_precision": 0.99,
                "minimum_known_coverage": 0.60,
                "maximum_unknown_false_naming_rate": 0.01,
            },
            "inputs": {key: str(path) for key, path in INPUTS.items()},
            "files": {str(path): digest(path) for path in (*INPUTS.values(), *helpers)},
            "inherited_validation": "detection_birth_extended.checked_inputs verifies every original execution binding; validate_frames verifies all5999 source/mask/stable-ID rows. Complete report and independent audit are additionally bound.",
            "libraries": {
                name: importlib.metadata.version(name) for name in ("numpy", "lap")
            },
            "no_model_or_video_decode": True,
            "preflight": "Independent source/hash audit required before run; no need for GPU.",
        },
    )
    print(digest(PROTOCOL))


def load_inputs():
    frozen = json.loads(PROTOCOL.read_text())
    for filename, expected in frozen["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed reciprocal control input: {filename}")
    if any(
        importlib.metadata.version(name) != version
        for name, version in frozen["libraries"].items()
    ):
        raise ValueError("Different scoring dependencies")
    protocol, clip, seeds, _ = checked_inputs(INPUTS["execution"])
    value = json.loads(INPUTS["streaming"].read_text())
    previous = json.loads(INPUTS["extension"].read_text())
    if (
        not value["complete"]
        or value["provenance"]["protocol_sha256"] != digest(INPUTS["execution"])
        or not previous["full_development_prefix_parity"]["exact"]
    ):
        raise ValueError("Require complete source-bound run and exact full prefix")
    if protocol["corroborator"]["settings"]["classes"] != [0]:
        raise ValueError("The control is limited to the original cow class")
    return frozen, protocol, clip, seeds, value


def run():
    output = RESULTS / "cutie-reciprocal-geometry.json"
    if output.exists():
        raise FileExistsError("Preserve complete prior outcomes")
    frozen, protocol, clip, seeds, value = load_inputs()
    validate_frames(value, clip, INPUTS["streaming"].parent)
    # No annotation arrays opened until the entire prediction transform is complete.
    transformed = {
        **value,
        "timeline": [substitute_frame(row) for row in value["timeline"]],
    }
    records, _ = annotations(SimpleNamespace(**INPUTS))
    slots = [*seeds["prompts"], {"cow": None}, {"cow": None}]

    def measure(prediction):
        return {
            str(start): score(
                prediction,
                records,
                clip,
                {**protocol, "score_seconds": (start, end)},
                slots,
                name_allowed=lambda frame, box: (
                    box.track_id in frame["named_track_ids"]
                ),
            )
            for start, end in WINDOWS
        }

    conditions = {"recorded_mask_slots": measure(value)}
    expected = (
        json.loads(INPUTS["development"].read_text())["conditions"]
        | json.loads(INPUTS["extension"].read_text())["conditions"]
    )
    for panel, baseline in conditions["recorded_mask_slots"].items():
        if baseline != expected[panel]:
            raise ValueError(f"Original strict baseline changed at panel {panel}")
    conditions["reciprocal_detector_bounds_same_slots"] = measure(transformed)
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(PROTOCOL),
        "baseline_exactly_reproduced": True,
        "unchanged_slots_names_and_temporal_decisions": True,
        "conditions": conditions,
        "acceptance": {
            name: {
                panel: acceptance(row, frozen["acceptance"])
                for panel, row in panels.items()
            }
            for name, panels in conditions.items()
        },
        "annotation_note": str(ROOT / "ANNOTATION_TEMPORAL_GEOMETRY.md"),
    }
    write_json(output, report)
    print(json.dumps(report["acceptance"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "preflight", "run"))
    action = parser.parse_args().action
    if action == "freeze":
        freeze()
    elif action == "preflight":
        load_inputs()
        print("Preflight passed; no labels or outcomes computed")
    else:
        run()
