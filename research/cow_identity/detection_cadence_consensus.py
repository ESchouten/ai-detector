"""Apply fixed reciprocal geometry confirmation to the completed five-fps control."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_box_consensus import prepare_conditions
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components, probability_gate, verified_mask
from detection_sam_tracking import score
from video_assessment import annotations


def load_inputs(args):
    contract = json.loads(args.protocol.read_text())
    for path, expected in contract["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Changed cadence consensus input: {path}")
    sources = {
        key: json.loads(Path(path).read_text())
        for key, path in contract["inputs"].items()
    }
    return contract, sources


def evaluate(args):
    contract, sources = load_inputs(args)
    value, raw, clip, baseline, protocol = (
        sources[key]
        for key in ("propagation", "corroborator", "clip", "baseline", "cadence")
    )
    if (
        not value["complete"]
        or value["stop_reason"] is not None
        or not raw["complete"]
        or len(value["frame_seconds"]) != 1529 * 5 + 1
        or baseline["propagation_sha256"]
        != digest(Path(contract["inputs"]["propagation"]))
        or baseline["protocol_sha256"] != digest(Path(contract["inputs"]["cadence"]))
        or [row["second"] for row in raw["timeline"]] != list(range(1530))
        or [row["second"] for row in value["timeline"]] != list(range(1530))
    ):
        raise ValueError(
            "Both complete source timelines and original quarantine are required"
        )
    frames = {row["second"]: row for row in clip["rows"]}
    for row in raw["timeline"]:
        source = frames[row["second"]]
        if (
            row["source_pixels_sha256"] != source["pixels_sha256"]
            or row["publisher_frame"] != source["publisher_frame"]
        ):
            raise ValueError(
                "One- and five-fps predictors did not see the same source pixels"
            )
    directory = Path(contract["inputs"]["propagation"]).parent
    changed = []
    for frame in value["timeline"]:
        mask = verified_mask(directory, frame, (clip["height"], clip["width"]), 8)
        cleaned, _ = largest_components(mask)
        changed.append({**frame, "boxes": boxes_from_mask(cleaned)})
    timelines, accepted = prepare_conditions({**value, "timeline": changed}, raw, 0.5)
    records, _ = annotations(args)
    quality = probability_gate(0.7)
    conflicts = baseline["conflicted_ids_by_second"]
    conditions = {}
    for name in (
        "quarantine_baseline",
        "maximum_confirmation",
        "reciprocal_confirmation",
    ):
        confirmations = (
            None
            if name == "quarantine_baseline"
            else accepted[
                "baseline" if name == "maximum_confirmation" else "reciprocal"
            ]
        )

        def allowed(frame, box, confirmations=confirmations):
            second = frame["second"]
            return (
                quality(frame, box)
                and box.track_id + 1 not in conflicts[str(second)]
                and (confirmations is None or box.track_id in confirmations[second])
            )

        conditions[name] = {
            str(window[0]): score(
                {**value, "timeline": timelines["baseline"]},
                records,
                clip,
                {**protocol, "score_seconds": window},
                value["provenance"]["seed_prompts"],
                name_allowed=allowed,
            )
            for window in protocol["comparison_windows"]
        }
    for label, source in baseline["conditions"].items():
        second = label.rsplit("_", 1)[1]
        if conditions["quarantine_baseline"][second] != source["quarantine"]:
            raise ValueError(
                "Every original five-fps baseline metric must reproduce exactly"
            )
    report = {
        "scope": contract["scope"],
        "protocol_sha256": digest(args.protocol),
        "conditions": conditions,
        "baseline_exactly_reproduced": True,
        "source_pixel_hashes_verified": len(raw["timeline"]),
    }
    write_json(args.output, report)
    print(json.dumps(conditions))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    evaluate(parser.parse_args())
