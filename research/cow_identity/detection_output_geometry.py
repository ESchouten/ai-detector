"""One exposed-data control: attach recorded names to actual detector geometry."""

import argparse
import importlib.metadata
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_reserved_score import acceptance, pooled_naming, validate_timeline
from video_assessment import VideoMetrics, annotations, truth_at

from aidetector.domain.models import BoundingBox, IdentityMatch

ROOT = Path(__file__).parent
PROTOCOL = ROOT / "detection_output_geometry_protocol.json"
RESULTS = ROOT / "results/2026-10-03/detection"
FILES = {
    "streaming": Path(".cache/cow-cutie/streaming-reserved/streaming.json"),
    "clip": Path(".cache/cow-cutie/reserved-2fps-clip/sampled.json"),
    "execution": ROOT / "detection_reserved_execution.json",
    "reserved_report": RESULTS / "cutie-streaming-reserved.json",
    "development_report": RESULTS / "cutie-streaming-development.json",
    "prefix_parity": RESULTS / "cutie-reserved-prefix-parity.json",
    "annotations": Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
    "source_pickle": Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
}
HELPERS = [
    "video_assessment.py",
    "detection_reserved_score.py",
    "detection_assessment.py",
    "detection_sam_tracking.py",
    "benchmark.py",
    "test_detection_output_geometry.py",
]


def baseline_boxes(frame, seeds):
    """Reproduce names actually emitted online, without replaying a policy."""
    result = []
    for item in frame["boxes"]:
        box = BoundingBox(**item)
        if box.track_id in frame["named_track_ids"]:
            cow = seeds[box.track_id]["cow"]
            box = replace(box, identity=IdentityMatch(f"{cow:032x}", f"Seed cow {cow}"))
        result.append(box)
    return result


def detector_boxes(frame, seeds):
    """Every actual proposal survives; a unique confirmed partner may name it."""
    named = set(frame["named_track_ids"])
    by_proposal = {}
    paired_slots = set()
    for pair in frame["reciprocal_pairs"]:
        slot, index = pair["track_id"], pair["proposal_index"]
        if slot not in named:
            continue
        if slot in paired_slots or index in by_proposal:
            raise ValueError("A recorded name has an ambiguous reciprocal partner")
        if not 0 <= index < len(frame["raw_detector_boxes"]):
            raise ValueError("A named partner is outside the recorded detector output")
        paired_slots.add(slot)
        by_proposal[index] = slot
    if paired_slots != named:
        raise ValueError("Every emitted name must have its original reciprocal partner")
    result = []
    for index, proposal in enumerate(frame["raw_detector_boxes"]):
        box = BoundingBox(**{**proposal, "track_id": None})
        if index in by_proposal:
            slot = by_proposal[index]
            cow = seeds[slot]["cow"]
            box = replace(
                box,
                track_id=slot,
                identity=IdentityMatch(f"{cow:032x}", f"Seed cow {cow}"),
            )
        result.append(box)
    return result


def measure(value, records, clip, windows, transform):
    results = {}
    seeds = value["provenance"]["seed_prompts"]
    for start, end in windows:
        metric = VideoMetrics()
        for frame in value["timeline"]:
            if not start <= frame["second"] <= end:
                continue
            boxes = transform(frame, seeds)
            truth = truth_at(
                records, frame["publisher_frame"], clip["width"], clip["height"]
            )
            metric.add(frame["second"], boxes, truth, [True] * len(boxes))
        summary = pooled_naming({"panel": {"naming_counts": dict(metric.counts)}})
        results[str(start)] = {**summary, "name_confusion": dict(metric.names)}
    return results


def freeze():
    if PROTOCOL.exists():
        raise ValueError("Do not overwrite the frozen geometry control")
    paths = [Path(__file__), *(ROOT / name for name in HELPERS)]
    paths.append(Path("detector/src/aidetector/domain/models.py"))
    write_json(
        PROTOCOL,
        {
            "scope": "One geometry control on five exposed panels; the previous reserved failure remains immutable. Seconds 3000 onward remain closed.",
            "windows": [
                [330, 629],
                [930, 1229],
                [1230, 1529],
                [1800, 2099],
                [2700, 2999],
            ],
            "conditions": ["recorded_mask_geometry", "all_actual_detector_proposals"],
            "policy": "Names, gates, reciprocal pairs, mask history and original slots are unchanged. Replace the output collection with every actual same-frame raw detector proposal. Attach a name only from its unique recorded reciprocal named slot; all other proposals have identity=None and track_id=None. Keep detector coordinates/confidence exactly. No extra filtering, selection, coordinate averaging or threshold search.",
            "evaluation": "Existing maximum-cardinality then IoU one-to-one assignment and VideoMetrics; preserve all annotations and all added/missed/unmatched/unknown predictions. Reproduce every baseline naming count and confusion on all five panels before accepting control results.",
            "tracking_caveat": "Unnamed stateless proposals have no asserted persistent track. Their track-switch counts are not comparable with Cutie's eight persistent slots; naming/localization counts remain comparable. No global ID-F1 claim.",
            "acceptance": {
                "minimum_conservative_precision": 0.99,
                "minimum_known_coverage": 0.60,
                "maximum_unknown_false_naming_rate": 0.01,
            },
            "files": {
                key: {"path": str(path), "sha256": digest(path)}
                for key, path in FILES.items()
            },
            "implementation": {str(path): digest(path) for path in paths},
            "scoring_libraries": {
                name: importlib.metadata.version(name) for name in ("numpy", "lap")
            },
            "input_pixels": "Reuse the completed 5999-input MPS run and exact development prefix; no decoding, models or new source access",
        },
    )


def load_inputs():
    frozen = json.loads(PROTOCOL.read_text())
    if any(
        importlib.metadata.version(name) != expected
        for name, expected in frozen["scoring_libraries"].items()
    ):
        raise ValueError("Frozen scoring dependencies changed")
    paths = frozen["implementation"] | {
        row["path"]: row["sha256"] for row in frozen["files"].values()
    }
    for path, expected in paths.items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen control input changed: {path}")
    data = {
        key: json.loads(path.read_text())
        for key, path in FILES.items()
        if path.suffix == ".json"
    }
    validate_timeline(data["streaming"], data["execution"], data["clip"])
    records, _ = annotations(SimpleNamespace(**FILES))
    return frozen, data, records


def run():
    frozen, data, records = load_inputs()
    value, clip = data["streaming"], data["clip"]
    conditions = {
        key: measure(value, records, clip, frozen["windows"], transform)
        for key, transform in (
            ("recorded_mask_geometry", baseline_boxes),
            ("all_actual_detector_proposals", detector_boxes),
        )
    }
    expected = (
        data["development_report"]["conditions"] | data["reserved_report"]["conditions"]
    )
    for key, result in conditions["recorded_mask_geometry"].items():
        if any(
            result[field] != expected[key][field]
            for field in (
                "naming_counts",
                "name_confusion",
                "known_coverage",
                "conservative_precision",
            )
        ):
            raise ValueError(f"Baseline differs from the original strict report: {key}")
    report = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(PROTOCOL),
        "conditions": conditions,
        "baseline_exactly_reproduced": True,
        "acceptance": {
            key: {
                panel: acceptance(row, frozen["acceptance"])
                for panel, row in results.items()
            }
            for key, results in conditions.items()
        },
        "no_reserved_claim": True,
        "selection": "No threshold sweep or additional operating point",
        "tracking_caveat": frozen["tracking_caveat"],
    }
    write_json(RESULTS / "cutie-output-geometry.json", report)
    print(
        json.dumps(
            {"acceptance": report["acceptance"], "baseline_exactly_reproduced": True}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    args = parser.parse_args()
    freeze() if args.action == "freeze" else run()
