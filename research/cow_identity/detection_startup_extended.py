"""One exposed0–2999 control extending the unchanged automatic startup driver."""

import argparse
import copy
import importlib.metadata
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from detection_reserved_score import (
    acceptance,
    pooled_naming,
    runtime_summary,
    validate_timeline,
)
from detection_sam_tracking import score
from detection_startup_control import (
    INSTALLED,
    initial_masks,
    prefix_clip,
    verify_files,
)
from detection_streaming import run as stream
from detection_streaming import validate_cadence
from detection_streaming_assessment import THRESHOLDS

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/detection"
STARTUP = ROOT / "detection_startup_control_v3_protocol.json"
STARTUP_REPORT = RESULTS / "startup-propagation.json"
STARTUP_RUN = Path(".cache/cow-startup-propagation/streaming.json")
FULL_CLIP = Path(".cache/cow-cutie/reserved-2fps-clip")
WINDOWS = [[330, 629], [930, 1229], [1230, 1529], [1800, 2099], [2700, 2999]]
POLICY_KEYS = (
    "source_commit",
    "libraries",
    "processing_fps",
    "seeded_cows",
    "naming",
    "recovery",
    "resource_limits",
    "max_internal_size",
    "mem_every",
    "use_long_term",
    "cache_reclaim_bytes",
)


def startup_inputs():
    """Keep the old freeze intact; resolve actual SDK modules after packaging.

    Installing the identical optional wheel adds a second namespace directory.
    Namespace count is not module provenance; the actual executed sources must
    still resolve to the original frozen installed copy.
    """
    original = json.loads(STARTUP.read_text())
    verify_files(original["files"])
    for name in (
        "cutie.inference.memory_manager",
        "cutie.inference.inference_core",
        "cutie.model.cutie",
    ):
        spec = importlib.util.find_spec(name)
        if (
            spec is None
            or spec.origin is None
            or not Path(spec.origin).resolve().is_relative_to(INSTALLED.resolve())
        ):
            raise ValueError("Use the frozen installed combined SDK modules")
    libraries = {
        name: importlib.metadata.version(name) for name in original["libraries"]
    }
    if libraries != original["libraries"]:
        raise ValueError("Installed libraries differ from the original app runtime")
    prefix = prefix_clip(
        json.loads((Path(original["inputs"]["clip"]) / "sampled.json").read_text()),
        original,
    )
    seeds = json.loads(Path(original["inputs"]["seed_manifest"]).read_text())
    masks, prompts, decision = initial_masks(seeds["source_frame"])
    with np.load(original["inputs"]["seed_masks"], allow_pickle=False) as archive:
        recorded = archive["masks"]
    if (
        not np.array_equal(recorded, masks)
        or prompts != seeds["prompts"]
        or decision != seeds["containment_decision"]
        or masks.shape != (8, prefix["height"], prefix["width"])
        or seeds["source_frame"]["source_pixels_sha256"]
        != prefix["rows"][0]["pixels_sha256"]
    ):
        raise ValueError("Original automatic startup selection changed")
    return original, prefix, masks, seeds, libraries


def anchors_from_report(report, labels):
    """Already completed frame0 association supplies names, never later labels."""
    anchors = {
        int(slot): cow for slot, cow in report["initial"]["geometry_anchors"].items()
    }
    if set(anchors) != set(range(len(labels))) or set(anchors.values()) != set(
        range(1, 9)
    ):
        raise ValueError("Require the completed eight unique initial geometry anchors")
    return [
        {"track_id": i, "anonymous_label": label, "cow": anchors[i]}
        for i, label in enumerate(labels)
    ]


def fixed_method(protocol, original):
    if any(protocol[key] != original[key] for key in POLICY_KEYS):
        raise ValueError(
            "Automatic startup changes no selected model or policy setting"
        )
    for key, value in original["inputs"].items():
        if key != "clip" and protocol["inputs"][key] != value:
            raise ValueError(
                "Initial masks, SDK and model inputs must remain unchanged"
            )
    if protocol["corroborator"]["settings"] != original["corroborator"]["settings"]:
        raise ValueError("Raw same-frame detector settings changed")
    if (
        protocol["last_processed_second"] != 2999
        or protocol["comparison_windows"] != WINDOWS
        or protocol["processing_fps"] != 2
    ):
        raise ValueError("Only the fixed exposed2999second control is allowed")
    anchors = anchors_from_report(
        json.loads(STARTUP_REPORT.read_text()), original["seeded_cows"]
    )
    named = [r["anonymous_label"] for r in anchors if r["cow"] <= 6]
    if protocol["initial_anchors"] != anchors or protocol["named_cows"] != named:
        raise ValueError(
            "Names must follow the supplied frame0 anchors, not slot order"
        )


def freeze(path):
    original, prefix, _, _, _ = startup_inputs()
    report = json.loads(STARTUP_REPORT.read_text())
    if report["protocol_sha256"] != digest(STARTUP) or report[
        "prediction_sha256"
    ] != digest(STARTUP_RUN):
        raise ValueError("Bind the completed original startup assessment")
    protocol = copy.deepcopy(original)
    anchors = anchors_from_report(report, original["seeded_cows"])
    protocol["inputs"].update(clip=str(FULL_CLIP))
    protocol.update(
        status="FROZEN_EXPOSED_AUTOMATIC_STARTUP_PENDING_GPU_RELEASE",
        frozen_at_utc=datetime.now(UTC).isoformat(),
        last_processed_second=2999,
        comparison_windows=WINDOWS,
        initial_anchors=anchors,
        named_cows=[r["anonymous_label"] for r in anchors if r["cow"] <= 6],
        anonymous_cows=[r["anonymous_label"] for r in anchors if r["cow"] > 6],
        scope="One continuous automatic-eight-mask startup control on exposed0–2999pixels. No threshold selection, births, retirement, new photos or later biological assignments.",
        scoring={
            "anchors": "Completed startup frame0 geometry association, frozen before this run; six known and two unknown biological IDs. This simulates initial enrollment, not farmer-confirmed names.",
            "denominator": "All original annotations and every output box in all five fixed300second panels; unchanged strict one-to-one IoU and99%precision/60%coverage/1%unknown criteria.",
            "prefix": "Every241input source record and121integer model/policy records must equal completed startup. Only emitted names differ, and must equal applying the original fixed gate to its recorded evidence and frozen known slots.",
        },
        prefix_parity="Exact source/masks/objects/raw detector/geometry/pairs/conflicts/config/backend prefix. No timing equality or half-second mask-cache claim; original driver caches masks only at1Hz.",
        output_contract="Unchanged joint driver: Cutie2Hz, rawYOLO1Hz, all eight original slots retained, original LCC geometry and same-frame fixed gate. Named labels areA–E/G, not the first six slots.",
        limitations=[
            "Allfive panels have already been exposed. This is a hypothesis-driven development control, not a new held-out test.",
            "Initial masks are automatic but initial biological labels are scoring-derived enrollment anchors, not demonstrated live farmer commands.",
            "Localization training includes early frames from this recording; startup generalization is not established.",
            "No later arrivals, retirement, reconnection, identity across visits or new-farm reliability demonstrated. Pixels at3000seconds and later stay closed.",
        ],
    )
    protocol["corroborator"]["seconds"] = {"start": 0, "stop": 2999, "step": 1}
    protocol["corroborator"]["mode"] = (
        "Actual same-frame raw YOLO1Hz, no cached substitution; complete joint live timing"
    )
    clip = json.loads((FULL_CLIP / "sampled.json").read_text())
    validate_cadence(clip, protocol)
    if (
        clip["rows"][:241] != prefix["rows"]
        or clip["contract"]["video_sha256"] != prefix["contract"]["video_sha256"]
    ):
        raise ValueError("Extended source must have the exact completed startup prefix")
    extra = [
        Path(__file__),
        ROOT / "test_detection_startup_extended.py",
        STARTUP,
        STARTUP_REPORT,
        STARTUP_RUN,
        RESULTS / "startup-propagation-independent-audit.json",
        RESULTS / "crowded-joint-readout.json",
        RESULTS / "crowded-joint-extended.json",
        FULL_CLIP / "sampled.json",
        FULL_CLIP / "sampled.avi",
    ]
    protocol["files"].update({str(p): digest(p) for p in extra})
    fixed_method(protocol, original)
    write_json(path, protocol)
    print(
        json.dumps(
            {
                "protocol_sha256": digest(path),
                "bindings": len(protocol["files"]),
                "named_labels": protocol["named_cows"],
            }
        )
    )


def checked(path):
    protocol = json.loads(path.read_text())
    verify_files(protocol["files"])
    original, prefix, masks, seeds, libraries = startup_inputs()
    fixed_method(protocol, original)
    clip_path = Path(protocol["inputs"]["clip"])
    clip = json.loads((clip_path / "sampled.json").read_text())
    validate_cadence(clip, protocol)
    if (
        clip["rows"][:241] != prefix["rows"]
        or digest(clip_path / "sampled.avi") != clip["clip_sha256"]
    ):
        raise ValueError("Source pixels or complete startup prefix changed")
    return protocol, clip, masks, seeds, libraries


def gate_names(frame, known_slots, minimum_p10):
    """Use recorded same-frame reciprocal evidence; no annotations or new scores."""
    p10 = {row["track_id"]: row["p10_probability"] for row in frame["objects"]}
    reciprocal = {row["track_id"] for row in frame["reciprocal_pairs"]}
    return [
        box["track_id"]
        for box in frame["boxes"]
        if box["track_id"] in known_slots & reciprocal
        and box["track_id"] + 1 not in frame["conflicted_ids"]
        and p10.get(box["track_id"], 0) >= minimum_p10
    ]


def prefix_parity(original, candidate, protocol):
    if (
        not original["complete"]
        or len(original["frame_samples"]) != 241
        or len(original["timeline"]) != 121
    ):
        raise ValueError("Require the complete original241input startup")
    fields = ("second", "publisher_frame", "pixels_sha256")
    differences = []
    for a, b in zip(
        original["frame_samples"], candidate["frame_samples"][:241], strict=True
    ):
        if any(a[key] != b[key] for key in fields):
            differences.append({"second": a["second"], "fields": ["input"]})
    known = {r["track_id"] for r in protocol["initial_anchors"] if r["cow"] <= 6}
    for a, b in zip(original["timeline"], candidate["timeline"][:121], strict=True):
        changed = [
            key for key in a if key != "named_track_ids" and a[key] != b.get(key)
        ]
        if a["named_track_ids"] or b["named_track_ids"] != gate_names(
            a, known, protocol["naming"]["minimum_p10"]
        ):
            changed.append("fixed_name_gate")
        if changed:
            differences.append({"second": a["second"], "fields": changed})
    metadata_equal = all(
        original[k] == candidate[k] for k in ("model_metadata", "config")
    )
    events_equal = original["quarantine_events"] == [
        r for r in candidate["quarantine_events"] if r["second"] <= 120
    ]
    return {
        "input_frames": 241,
        "integer_masks": 121,
        "differences": differences,
        "model_config_equal": metadata_equal,
        "quarantine_events_equal": events_equal,
        "exact_except_predeclared_names": not differences
        and metadata_equal
        and events_equal,
    }


def verify_geometry(value, directory, shape):
    for frame in value["timeline"]:
        path = directory / "masks" / f"{frame['second']}.png"
        if digest(path) != frame["mask_sha256"]:
            raise ValueError("Saved indexed mask changed")
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if (
            mask is None
            or mask.shape != shape
            or not set(np.unique(mask)) <= set(range(9))
        ):
            raise ValueError("Mask contains an unsupported stable slot")
        clean, _ = largest_components(mask)
        keys = ("x1", "y1", "x2", "y2", "track_id")
        if [[b[k] for k in keys] for b in boxes_from_mask(clean)] != [
            [b[k] for k in keys] for b in frame["boxes"]
        ]:
            raise ValueError("Original LCC mask geometry changed")


def exposed_truth():
    path = Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz")
    with np.load(path, allow_pickle=False) as arrays:
        metadata = json.loads(str(arrays["metadata_json"]))
        keep = (arrays["frame_id"] >= 1) & (arrays["frame_id"] <= 59981)
        records = {
            key: arrays[key][keep]
            for key in ("frame_id", "cow_id", "x_center", "y_center", "width", "height")
        }
    if metadata[
        "coordinate_convention"
    ] != "normalized-center-width-height" or metadata["source_sha256"] != digest(
        Path("datasets/8-calves/video/pmfeed_4_3_16.pkl")
    ):
        raise ValueError("Safe annotation provenance changed")
    return records


def run(args):
    protocol, clip, masks, seeds, libraries = checked(args.protocol)
    args.frames = None
    try:
        stream(args, protocol, clip, masks, seeds, libraries)
    finally:
        path = args.output / "streaming.json"
        if path.exists():
            value = json.loads(path.read_text())
            value["provenance"].update(
                identity_origin="Automatic eight-mask startup; named opaque labels come only from the completed frame0 scoring anchors frozen before this run. No future identity assignment or farmer-confirmation claim.",
                startup_extended_runner_sha256=digest(Path(__file__)),
            )
            write_json(path, value)


def assess(args):
    protocol, clip, _, seeds, _ = checked(args.protocol)
    path = args.output / "streaming.json"
    value = json.loads(path.read_text())
    if (
        value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or value["provenance"]["libraries"] != protocol["libraries"]
        or value["provenance"]["seed_prompts"] != seeds["prompts"]
    ):
        raise ValueError("Execution provenance changed")
    if not value["complete"]:
        write_json(
            args.report,
            {
                "status": "FAILED_INCOMPLETE",
                "stop_reason": value["stop_reason"],
                "scores": None,
                "prediction_sha256": digest(path),
                "protocol_sha256": digest(args.protocol),
            },
        )
        return
    validate_timeline(value, protocol, clip)
    verify_geometry(value, args.output, (clip["height"], clip["width"]))
    original = json.loads(STARTUP_RUN.read_text())
    verify_geometry(original, STARTUP_RUN.parent, (clip["height"], clip["width"]))
    parity = prefix_parity(original, value, protocol)
    if not parity["exact_except_predeclared_names"]:
        write_json(
            args.report,
            {
                "status": "FAILED_PREFIX_PARITY",
                "scores": None,
                "prefix_parity": parity,
                "prediction_sha256": digest(path),
                "protocol_sha256": digest(args.protocol),
            },
        )
        return
    # Only after complete prediction/provenance/geometry/prefix checks enter truth.
    records = exposed_truth()
    scoring = {**protocol, "named_cows": list(range(1, 7))}
    conditions = {
        str(window[0]): score(
            value,
            records,
            clip,
            {**scoring, "score_seconds": window},
            protocol["initial_anchors"],
            name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
        )
        for window in WINDOWS
    }
    baseline = {}
    for name in ("crowded-joint-readout.json", "crowded-joint-extended.json"):
        baseline.update(json.loads((RESULTS / name).read_text())["conditions"])
    report = {
        "status": "COMPLETE",
        "scope": protocol["scope"],
        "protocol_sha256": digest(args.protocol),
        "prediction_sha256": digest(path),
        "initial_anchors": protocol["initial_anchors"],
        "prefix_parity": parity,
        "conditions": conditions,
        "pooled": pooled_naming(conditions),
        "acceptance": {
            key: acceptance(row, THRESHOLDS) for key, row in conditions.items()
        },
        "thresholds": THRESHOLDS,
        "six_seed_births_baseline": baseline,
        "runtime_joint_live": runtime_summary(value, 2),
        "limitations": protocol["limitations"],
    }
    write_json(args.report, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "acceptance", "pooled", "prefix_parity")
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "verify", "run", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve existing freezes")
        freeze(args.protocol)
    elif args.mode == "verify":
        protocol, clip, masks, _, _ = checked(args.protocol)
        print(
            json.dumps(
                {
                    "bindings": len(protocol["files"]),
                    "inputs": len(clip["rows"]),
                    "masks": len(masks),
                }
            )
        )
    elif args.mode == "run":
        if args.output is None or args.output.exists():
            parser.error("A fresh output directory is required")
        run(args)
    else:
        if args.output is None or args.report is None or args.report.exists():
            parser.error("An existing run directory and fresh report path are required")
        assess(args)


if __name__ == "__main__":
    main()
