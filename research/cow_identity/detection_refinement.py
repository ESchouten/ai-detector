"""Run a fixed CPU SAM refinement control without changing Cutie tracking state."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components, probability_gate, verified_mask
from detection_initialization import draw
from detection_sam_tracking import score
from video_assessment import annotations, detector_libraries, pixels_hash, read_frame


def refine(model, image, original, settings):
    prompts = [[row[key] for key in ("x1", "y1", "x2", "y2")] for row in original]
    result = model.predict(image, bboxes=prompts, verbose=False, **settings)[0]
    masks = result.masks.data.cpu().numpy() > 0.5
    if masks.shape != (len(original), *image.shape[:2]):
        raise ValueError("SAM changed the original prompt-slot count or shape")
    boxes = []
    for source, mask in zip(original, masks, strict=True):
        rows = boxes_from_mask(mask.astype(np.uint8))
        if rows:
            boxes.append({**rows[0], "track_id": source["track_id"]})
    return boxes, masks


def infer(args, value, clip, protocol):
    import torch
    from ultralytics import SAM

    torch.set_num_threads(2)
    model = SAM(str(args.model))
    capture = cv2.VideoCapture(str(args.video))
    cached = []
    try:
        for second in protocol["seconds"]:
            source = value["timeline"][second]
            mask = verified_mask(
                args.propagation.parent, source, (clip["height"], clip["width"]), 8
            )
            cleaned, _ = largest_components(mask)
            original = boxes_from_mask(cleaned)
            _, image = read_frame(capture, second, clip["source_fps"])
            expected = next(row for row in clip["rows"] if row["second"] == second)
            if pixels_hash(image) != expected["pixels_sha256"]:
                raise ValueError("Decoded source changed from the original Cutie frame")
            started = time.perf_counter()
            refined, masks = refine(model, image, original, protocol["settings"])
            elapsed = time.perf_counter() - started
            mask_path = args.output / f"{second}-masks.npz"
            np.savez_compressed(
                mask_path, masks=masks, track_ids=[row["track_id"] for row in original]
            )
            frames = [
                draw(
                    image,
                    [[r[k] for k in ("x1", "y1", "x2", "y2")] for r in rows],
                    [f"Slot {r['track_id'] + 1}" for r in rows],
                    (0, 180, 255),
                )
                for rows in (original, refined)
            ]
            preview = args.output / f"{second}-comparison.jpg"
            if not cv2.imwrite(str(preview), cv2.hconcat(frames)):
                raise ValueError("Could not save refinement preview")
            cached.append(
                {
                    "second": second,
                    "original": original,
                    "refined": refined,
                    "source_pixels_sha256": pixels_hash(image),
                    "mask_sha256": digest(mask_path),
                    "preview_sha256": digest(preview),
                    "elapsed_seconds": elapsed,
                }
            )
            print(json.dumps({"second": second, "seconds": elapsed}), flush=True)
    finally:
        capture.release()
    parameter = next(model.predictor.model.parameters())
    return {
        "rows": cached,
        "actual_device": str(parameter.device),
        "actual_dtype": str(parameter.dtype),
        "libraries": detector_libraries(),
    }


def measure(value, cached, clip, source_protocol, protocol, quarantine, records):
    quality = probability_gate(protocol["minimum_p10_probability"])

    def allowed(frame, box):
        return (
            quality(frame, box)
            and box.track_id + 1
            not in quarantine["conflicted_ids_by_second"][str(frame["second"])]
        )

    conditions = {}
    for variant in ("original", "refined"):
        changed = {row["second"]: row[variant] for row in cached["rows"]}
        timeline = [
            {**row, "boxes": changed.get(row["second"], row["boxes"])}
            for row in value["timeline"]
        ]
        counts, names, frames = Counter(), Counter(), []
        for second in protocol["seconds"]:
            metrics = score(
                {**value, "timeline": timeline},
                records,
                clip,
                {**source_protocol, "score_seconds": [second, second]},
                value["provenance"]["seed_prompts"],
                name_allowed=allowed,
            )
            counts.update(metrics["naming_counts"])
            names.update(metrics["name_confusion"])
            frames.append({"second": second, "counts": metrics["naming_counts"]})
        named = sum(
            counts[key]
            for key in (
                "correct_name",
                "wrong_name",
                "unknown_named",
                "unmatched_named",
            )
        )
        conditions[variant] = {
            "counts": dict(counts),
            "name_confusion": dict(names),
            "frames": frames,
            "known_coverage": counts["correct_name"] / counts["visible_known"],
            "conservative_precision": counts["correct_name"] / named if named else 0,
            "unknown_false_naming_rate": counts["unknown_named"]
            / counts["visible_unknown"],
        }
    return conditions


def load_inputs(args, protocol):
    for name, key in (
        ("propagation", "propagation_sha256"),
        ("quarantine", "quarantine_report_sha256"),
        ("source_protocol", "source_protocol_sha256"),
        ("model", "sam_sha256"),
        ("video", "video_sha256"),
    ):
        if digest(getattr(args, name)) != protocol[key]:
            raise ValueError(f"Changed frozen input {name}")
    value = json.loads(args.propagation.read_text())
    source = json.loads(args.source_protocol.read_text())
    clip = json.loads(args.sampled_manifest.read_text())
    if (
        not value["complete"]
        or digest(args.sampled_manifest) != source["sampled_manifest_sha256"]
    ):
        raise ValueError("Missing completed source inference or changed source pixels")
    if [row["second"] for row in value["timeline"]] != list(range(1530)):
        raise ValueError("The complete original timeline is required")
    return value, source, clip, json.loads(args.quarantine.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "propagation",
        "source-protocol",
        "sampled-manifest",
        "quarantine",
        "model",
        "video",
        "annotations",
        "source-pickle",
        "output",
        "report",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    path = Path(__file__).with_name("detection_refinement_protocol.json")
    protocol = json.loads(path.read_text())
    value, source, clip, quarantine = load_inputs(args, protocol)
    manifest = args.output / "predictions.json"
    provenance = {
        "protocol_sha256": digest(path),
        "runner_sha256": digest(Path(__file__)),
        "libraries": detector_libraries(),
    }
    if manifest.exists():
        cached = json.loads(manifest.read_text())
        if cached["provenance"] != provenance:
            parser.error(
                "Refinement cache provenance changed; choose a fresh output directory"
            )
    else:
        args.output.mkdir(parents=True)
        cached = {**infer(args, value, clip, protocol), "provenance": provenance}
        write_json(manifest, cached)
    if [row["second"] for row in cached["rows"]] != protocol["seconds"]:
        parser.error("Refinement cache must contain all thirty frozen frames")
    records, metadata = annotations(args)
    if metadata["source_sha256"] != source["source_annotations_sha256"]:
        parser.error("Changed publisher labels")
    result = {
        "protocol": protocol,
        **provenance,
        "predictions_sha256": digest(manifest),
        "annotations_sha256": digest(args.annotations),
        "scorer_sha256": digest(Path(__file__).with_name("detection_sam_tracking.py")),
        "conditions": measure(
            value, cached, clip, source, protocol, quarantine, records
        ),
        "inference_seconds": sum(row["elapsed_seconds"] for row in cached["rows"]),
    }
    write_json(args.report, result)
    print(json.dumps(result["conditions"]))


if __name__ == "__main__":
    main()
