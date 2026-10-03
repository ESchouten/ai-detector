"""Strict unchanged entry metrics, with all dynamically born anonymous slots."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from passage_entry_birth_run import checked_inputs
from passage_entry_score import measure


def validate_attempts(frame):
    for attempt in frame["sam_attempts"]:
        if digest(Path(attempt["cache"])) != attempt["cache_sha256"]:
            raise ValueError("Saved birth attempt masks changed")
    if sum(a["accepted"] for a in frame["sam_attempts"]) != len(frame["born_ids"]):
        raise ValueError("Birth count differs from accepted current prompts")


def validate_masks(value, source, directory):
    areas, stable_ids, births = {}, {1}, []
    for index, (frame, original) in enumerate(
        zip(value["timeline"], source["rows"], strict=True)
    ):
        if (
            frame["sequence_frame"] != index
            or frame["source_frame"] != original["source_frame"]
            or frame["source_pixels_sha256"] != original["pixels_sha256"]
        ):
            raise ValueError("Birth prediction source or chronology differs")
        added = frame["born_ids"]
        if added != list(range(max(stable_ids) + 1, max(stable_ids) + len(added) + 1)):
            raise ValueError("Anonymous stable IDs must be monotonic and never reused")
        stable_ids.update(added)
        if {int(k) for k in frame["object_to_channel"]} != stable_ids:
            raise ValueError("Live stable object registry differs from declared births")
        path = directory / "masks" / f"{index:03d}.png"
        if digest(path) != frame["mask_sha256"]:
            raise ValueError("A propagated indexed mask changed")
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if mask.shape != (720, 1280) or not set(np.unique(mask)).issubset(
            {0, *stable_ids}
        ):
            raise ValueError("Unexpected mask geometry or an undeclared object")
        keys = ("track_id", "x1", "y1", "x2", "y2")
        derived = boxes_from_mask(largest_components(mask)[0])
        if [[b[k] for k in keys] for b in derived] != [
            [b[k] for k in keys] for b in frame["boxes"]
        ]:
            raise ValueError("Published geometry differs from its original mask")
        validate_attempts(frame)
        areas[frame["second"]] = int(np.count_nonzero(mask))
        births.extend(
            {"second": frame["second"], "stable_id": i, "name": None} for i in added
        )
    return areas, births


def score(args):
    protocol, source = checked_inputs(args.protocol)
    value = json.loads(args.predictions.read_text())
    truth = json.loads(Path(protocol["inputs"]["annotations"]).read_text())
    if not value["complete"] or value["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Complete output from the exact frozen birth method required")
    if value["libraries"] != protocol["libraries"] or truth[
        "source_manifest_sha256"
    ] != digest(Path(protocol["inputs"]["frames"])):
        raise ValueError("Runtime or annotation provenance changed")
    areas, births = validate_masks(value, source, args.predictions.parent)
    report = measure(value["timeline"], truth["frames"], areas)
    counts = report["overall"]["counts"]
    if (counts["frames"], counts["visible_known"], counts["visible_unknown"]) != (
        22,
        9,
        14,
    ):
        raise ValueError("Original lifecycle scoring denominators changed")
    report.update(
        births=births,
        total_created_slots=1 + len(births),
        sam_prompt_count=sum(len(r["sam_attempts"]) for r in value["timeline"]),
        elapsed_seconds=value["elapsed_seconds"],
        sources={
            str(p): digest(p) for p in (args.protocol, args.predictions, Path(__file__))
        },
    )
    write_json(args.output, report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("overall", "lifecycle", "births", "sam_prompt_count")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "predictions", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    score(parser.parse_args())
