"""Score all 22 entry/exit observations without changing lifecycle denominators."""

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from passage_entry_control import checked_protocol
from passage_metrics import rates, score_frame


def named_prediction(frame):
    named = frame["named_track_ids"]
    if not set(named).issubset({0}) or len(named) != len(set(named)):
        raise ValueError("Only the original reviewed animal may receive a name")
    return {
        **frame,
        "boxes": [
            {
                **box,
                "identity": {
                    "identity_id": format(5676, "x")
                    if box["track_id"] in named
                    else None
                },
            }
            for box in frame["boxes"]
        ],
    }


def measure(timeline, annotations, areas):
    if [r["second"] for r in timeline] != [i / 2 for i in range(22)]:
        raise ValueError("Scoring requires all half-second frames exactly once")
    if [r["second"] for r in annotations] != [i / 2 for i in range(22)]:
        raise ValueError("Annotations must cover all 22 timestamps")
    total, definite = Counter(), Counter()
    outcomes = []
    for row, truth in zip(timeline, annotations, strict=True):
        predicted = named_prediction(row)
        counts, decisions = score_frame(predicted, truth, {5676})
        total.update(counts)
        subset, _ = score_frame(predicted, truth, {5676}, include_uncertain=False)
        definite.update(subset)
        outcomes.append(
            {
                "second": row["second"],
                "counts": dict(counts),
                "decisions": decisions,
                "mask_pixels": areas[row["second"]],
                "empty_truth": not truth["boxes"],
            }
        )
    empty = [r for r in outcomes if r["empty_truth"]]
    return {
        "overall": rates(total),
        "definite_annotation_sensitivity": rates(definite),
        "lifecycle": {
            "inherited_name_on_entrant": total["unknown_named"],
            "named_unmatched": total["unmatched_named"],
            "names_in_empty_frames": sum(r["counts"]["unmatched_named"] for r in empty),
            "empty_frames_with_any_mask_pixels": sum(
                r["mask_pixels"] > 0 for r in empty
            ),
            "last_nonempty_mask_second": max(
                (t for t, area in areas.items() if area), default=None
            ),
            "last_named_second": max(
                (r["second"] for r in timeline if r["named_track_ids"]), default=None
            ),
            "final_mask_pixels": areas[10.5],
        },
        "timeline": outcomes,
        "limitation": "Development lifecycle replay, one initial animal and one entrant. AI-reviewed publisher-linked labels; no field reliability or re-identification claim. Main scores retain uncertain fragments, missing predictions and empty frames.",
    }


def score(args):
    protocol, source = checked_protocol(args.protocol)
    value = json.loads(args.predictions.read_text())
    annotations = json.loads(Path(protocol["inputs"]["annotations"]).read_text())
    if not value["complete"] or value["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Incomplete predictions or a different execution freeze")
    if value["libraries"] != protocol["libraries"]:
        raise ValueError("Execution library versions differ")
    if annotations["source_manifest_sha256"] != digest(
        Path(protocol["inputs"]["frames"])
    ):
        raise ValueError("Annotation provenance differs from the selected source")
    areas = {}
    for index, (frame, row) in enumerate(
        zip(value["timeline"], source["rows"], strict=True)
    ):
        if (
            frame["sequence_frame"] != index
            or frame["source_frame"] != row["source_frame"]
            or frame["source_pixels_sha256"] != row["pixels_sha256"]
        ):
            raise ValueError("Prediction source or chronology changed")
        path = args.predictions.parent / "masks" / f"{index:03d}.png"
        if digest(path) != frame["mask_sha256"]:
            raise ValueError("Propagated mask file changed")
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if mask.shape != (720, 1280) or not set(np.unique(mask)).issubset({0, 1}):
            raise ValueError("Unexpected mask size or invented object slot")
        derived = boxes_from_mask(largest_components(mask)[0])
        keys = ("track_id", "x1", "y1", "x2", "y2")
        if [[b[k] for k in keys] for b in derived] != [
            [b[k] for k in keys] for b in frame["boxes"]
        ]:
            raise ValueError("Reported geometry differs from its own mask")
        areas[frame["second"]] = int(np.count_nonzero(mask))
    result = measure(value["timeline"], annotations["frames"], areas)
    counts = result["overall"]["counts"]
    if (counts["frames"], counts["visible_known"], counts["visible_unknown"]) != (
        22,
        9,
        14,
    ):
        raise ValueError("The complete frozen lifecycle denominators changed")
    result["sources"] = {
        str(p): digest(p) for p in (args.protocol, args.predictions, Path(__file__))
    }
    write_json(args.output, result)
    print(json.dumps({"overall": result["overall"], "lifecycle": result["lifecycle"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "predictions", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    score(parser.parse_args())
