"""Score fixed initial anonymous associations only after complete startup inference."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask, indexed_seed
from detection_cutie_variants import largest_components
from detection_reserved_score import runtime_summary
from detection_startup_control import checked
from detection_tracking import summarize
from video_assessment import pair_boxes, truth_at

from aidetector.domain.models import BoundingBox


def initial_associations(initial_boxes, truth):
    """Associate once; duplicate/unmatched initial slots never acquire an anchor."""
    matches = pair_boxes(initial_boxes, truth)
    return {initial_boxes[i].track_id: truth[j]["cow"] for i, j in matches.items()}


def scoring_truth():
    """Materialize only the0–120second numeric panel; never unpickle source data."""
    directory = Path("datasets/8-calves/video")
    with np.load(directory / "pmfeed_4_3_16.safe-v1.npz", allow_pickle=False) as arrays:
        metadata = json.loads(str(arrays["metadata_json"]))
        keep = (arrays["frame_id"] >= 1) & (arrays["frame_id"] <= 2401)
        records = {
            key: arrays[key][keep]
            for key in ("frame_id", "cow_id", "x_center", "y_center", "width", "height")
        }
    if (
        metadata["source_sha256"] != digest(directory / "pmfeed_4_3_16.pkl")
        or metadata["coordinate_convention"] != "normalized-center-width-height"
    ):
        raise ValueError("Unexpected safe publisher annotation provenance")
    return records


def continuity_counts(timeline, anchors):
    counts = Counter(
        {
            key: 0
            for key in (
                "visible_annotations",
                "predictions",
                "matched",
                "missed_annotations",
                "correct_initial_instance",
                "wrong_initial_instance",
                "unmatched_anchored",
                "matched_unanchored",
                "unmatched_unanchored",
            )
        }
    )
    slots = defaultdict(Counter)
    errors = []
    for frame in timeline:
        boxes = [BoundingBox(**box) for box in frame["boxes"]]
        truth = frame["truth"]
        matches = pair_boxes(boxes, truth)
        counts.update(
            visible_annotations=len(truth),
            predictions=len(boxes),
            matched=len(matches),
            missed_annotations=len(truth) - len(matches),
        )
        for i, box in enumerate(boxes):
            anchor = anchors.get(box.track_id)
            actual = truth[matches[i]]["cow"] if i in matches else None
            if anchor is None:
                outcome = (
                    "matched_unanchored"
                    if actual is not None
                    else "unmatched_unanchored"
                )
            elif actual is None:
                outcome = "unmatched_anchored"
            else:
                outcome = (
                    "correct_initial_instance"
                    if actual == anchor
                    else "wrong_initial_instance"
                )
            counts[outcome] += 1
            slots[str(box.track_id)][outcome] += 1
            if outcome != "correct_initial_instance":
                errors.append(
                    {
                        "second": frame["second"],
                        "track": box.track_id,
                        "initial_anchor": anchor,
                        "matched_animal": actual,
                        "outcome": outcome,
                    }
                )
    attempts = sum(
        counts[k]
        for k in (
            "correct_initial_instance",
            "wrong_initial_instance",
            "unmatched_anchored",
        )
    )
    return {
        "counts": dict(counts),
        "per_slot": {slot: dict(value) for slot, value in slots.items()},
        "initial_instance_coverage": counts["correct_initial_instance"]
        / counts["visible_annotations"]
        if counts["visible_annotations"]
        else 0,
        "anchored_precision": counts["correct_initial_instance"] / attempts
        if attempts
        else 0,
        "errors": errors,
    }


def validate_complete(value, clip, protocol_path):
    if not value["complete"] or value["stop_reason"]:
        raise ValueError(
            "An incomplete startup run cannot establish full-panel quality"
        )
    if value["provenance"]["protocol_sha256"] != digest(protocol_path):
        raise ValueError("Prediction protocol differs from scoring freeze")
    if [row["second"] for row in value["timeline"]] != list(range(121)) or len(
        value["frame_seconds"]
    ) != 241:
        raise ValueError("All241inputs and121integer outputs are required")
    if [r["second"] for r in value["frame_samples"]] != [
        r["second"] for r in clip["rows"]
    ]:
        raise ValueError("Processed source cadence differs from freeze")
    for actual, source in zip(value["frame_samples"], clip["rows"], strict=True):
        if (
            actual["pixels_sha256"] != source["pixels_sha256"]
            or actual["publisher_frame"] != source["publisher_frame"]
        ):
            raise ValueError("Processed source pixels or index differ")
    for actual, source in zip(value["timeline"], clip["rows"][::2], strict=True):
        if (
            actual["named_track_ids"]
            or actual["source_pixels_sha256"] != source["pixels_sha256"]
            or actual["publisher_frame"] != source["publisher_frame"]
        ):
            raise ValueError("Anonymous output or exact source binding changed")
    metadata = value["model_metadata"]
    if (
        metadata["cutie_device"] not in ("mps", "mps:0")
        or metadata["cutie_dtype"] != "torch.float32"
        or metadata["yolo_device"] not in ("mps", "mps:0")
        or not metadata["yolo_fp16"]
    ):
        raise ValueError("Frozen actual MPS model precision is required")


def assess(args):
    protocol, clip, masks, seeds, _ = checked(args.protocol)
    path = args.predictions / "streaming.json"
    value = json.loads(path.read_text())
    validate_complete(value, clip, args.protocol)
    for frame in value["timeline"]:
        mask_path = args.predictions / "masks" / f"{frame['second']}.png"
        if digest(mask_path) != frame["mask_sha256"]:
            raise ValueError("Saved original mask changed")
        clean, _ = largest_components(cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED))
        actual = [
            {k: b[k] for k in ("x1", "y1", "x2", "y2", "track_id")}
            for b in frame["boxes"]
        ]
        expected = [
            {k: b[k] for k in ("x1", "y1", "x2", "y2", "track_id")}
            for b in boxes_from_mask(clean)
        ]
        if actual != expected:
            raise ValueError("Reported boxes differ from original-mask LCC geometry")
    # Publisher arrays enter only after complete, source-bound predictions.
    records = scoring_truth()
    initial_truth = truth_at(records, 1, clip["width"], clip["height"])
    clean, _ = largest_components(indexed_seed(masks))
    initial_boxes = [BoundingBox(**row) for row in boxes_from_mask(clean)]
    anchors = initial_associations(initial_boxes, initial_truth)
    timeline = [
        {
            **frame,
            "truth": truth_at(
                records, frame["publisher_frame"], clip["width"], clip["height"]
            ),
        }
        for frame in value["timeline"][1:]
    ]
    result = {
        "protocol_sha256": digest(args.protocol),
        "prediction_sha256": digest(path),
        "scope": protocol["scope"],
        "scoring": protocol["scoring"],
        "initial": {
            "slots": seeds["prompts"],
            "geometry_anchors": anchors,
            "initial_truth_count": len(initial_truth),
        },
        "continuity": continuity_counts(timeline, anchors),
        "tracking": summarize({"timeline": timeline}),
        "runtime": runtime_summary(value, protocol["processing_fps"]),
        "actual_models": value["model_metadata"],
        "all_output_names_empty": True,
    }
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "initial_anchors": len(anchors),
                "counts": result["continuity"]["counts"],
                "runtime": result["runtime"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve the original assessment")
    assess(args)
