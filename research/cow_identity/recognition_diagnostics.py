"""Decompose calibration naming losses and test label-free foreground bounds.

This is a diagnostic, not a replacement for the frozen original evaluation.
It does not alter crops, embeddings, track IDs, or ground-truth annotations.
"""

import argparse
import copy
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from recognition_fusion import observation_key
from recognition_temporal import clear_collisions, smoothed_scores, update_track
from tracked_experiment import (
    PROTOCOL,
    read_features,
    summarize,
    validate_gallery,
    validate_panel,
    validate_representation,
)
from video_assessment import pair_boxes, pixels_hash

from aidetector.domain.models import BoundingBox


def foreground_bounds(image, box):
    """Approximate retained SAM foreground from the lossless gray-background PNG."""
    x1, y1, x2, y2 = box
    if image.shape[:2] != (y2 - y1, x2 - x1):
        raise ValueError("Masked crop and original bounding box dimensions differ")
    ys, xs = np.nonzero(np.any(image != 127, axis=2))
    if not len(xs):
        return list(box)
    return [
        x1 + int(xs.min()),
        y1 + int(ys.min()),
        x1 + int(xs.max()) + 1,
        y1 + int(ys.max()) + 1,
    ]


def tightened_manifest(manifest, source):
    crops = json.loads((source / "crops.json").read_text())
    if len(crops["rows"]) != len(manifest["rows"]):
        raise ValueError("Foreground control must retain every predicted box")
    result = copy.deepcopy(manifest)
    for original, row, crop in zip(
        manifest["rows"], result["rows"], crops["rows"], strict=True
    ):
        if observation_key(original) != observation_key(crop):
            raise ValueError("Foreground crops do not align with prediction rows")
        variant = crop["variants"]["masked"]
        image = cv2.imread(str(source / variant["path"]))
        if image is None or pixels_hash(image) != variant["pixels_sha256"]:
            raise ValueError("Foreground crop pixels changed")
        row["box"] = foreground_bounds(image, original["box"])
        row["original_box"] = original["box"]
    # Reassociate every output rectangle, independently of predictions or names.
    for frame in result["frames"]:
        rows = [result["rows"][i] for i in frame["rows"]]
        boxes = [
            BoundingBox(*row["box"], "cow", row["confidence"], row["track"])
            for row in rows
        ]
        pairs = pair_boxes(boxes, frame["truth"])
        for i, row in enumerate(rows):
            row["truth"] = frame["truth"][pairs[i]]["cow"] if i in pairs else None
    return result


def staged_names(rows, scores, threshold, margin):
    accepted = (scores.similarity >= threshold) & (scores.margin >= margin)
    candidates = np.where(accepted, scores.predicted, 0)
    conflict_free = candidates.copy()
    before_collision = np.zeros(len(rows), dtype=int)
    confirmed = np.zeros(len(rows), dtype=int)
    state = {}
    pending = []
    for i, row in enumerate(rows):
        confirmed[i] = update_track(state, row, int(candidates[i]), 0)
        before_collision[i] = confirmed[i]
        pending.append((i, row["track"]))
        if i + 1 == len(rows) or rows[i + 1]["second"] != row["second"]:
            indices = np.array([j for j, _ in pending])
            identities, counts = np.unique(candidates[indices], return_counts=True)
            duplicates = identities[(counts > 1) & (identities != 0)]
            conflict_free[indices[np.isin(candidates[indices], duplicates)]] = 0
            clear_collisions(confirmed, pending, state)
            pending = []
    return {
        "rank1_without_rejection": np.where(
            scores.similarity > -1, scores.predicted, 0
        ),
        "threshold_and_margin": candidates,
        "candidate_conflict_rejection_only": conflict_free,
        "three_observations_before_current_frame_collision": before_collision,
        "three_observations_with_collision_rejection": confirmed,
    }


def diagnose(args):
    gallery_manifest, gallery = read_features(args.gallery)
    manifest, vectors = read_features(args.queries)
    protocol = json.loads(PROTOCOL.read_text())
    validate_gallery(gallery_manifest, protocol)
    validate_panel(manifest, gallery_manifest, "calibration", protocol)
    validate_representation(gallery_manifest, manifest, "calibration")
    if {row["second"] for row in manifest["rows"]} != set(range(1230, 1530)):
        raise ValueError("This diagnostic is calibration-only")
    owners = np.array([row["cow"] for row in gallery_manifest["rows"]])
    if len(owners) != 60 or any(np.sum(owners == cow) != 10 for cow in range(1, 7)):
        raise ValueError("Diagnostic requires the frozen 60-photo gallery")
    rows = [
        {**row, "cow": row["truth"] if row["truth"] is not None else -1}
        for row in manifest["rows"]
    ]
    stages = {}
    raw = smoothed_scores(rows, vectors, gallery, owners, 1.0, "none")
    for geometry in ("none", "0.2", "0.5"):
        scores = smoothed_scores(rows, vectors, gallery, owners, 0.5, geometry)
        names = staged_names(rows, scores, 0.55, 0.20)
        stages[geometry] = {
            key: summarize(manifest, value) for key, value in names.items()
        }
    tightened = tightened_manifest(manifest, args.crops)
    scores = smoothed_scores(rows, vectors, gallery, owners, 0.5, "none")
    names = staged_names(rows, scores, 0.55, 0.20)
    result = {
        "status": "Exploratory calibration diagnosis; original benchmark scores unchanged",
        "gallery_sha256": digest(args.gallery / "manifest.json"),
        "queries_sha256": digest(args.queries / "manifest.json"),
        "crops_sha256": digest(args.crops / "crops.json"),
        "policy": "Fixed baseline EMA0.5, similarity0.55, margin0.20, TTL0; all three geometries reported without selection",
        "raw_rank1_without_rejection": summarize(manifest, raw.predicted),
        "stages": stages,
        "foreground_bounds_control": {
            "limitation": "Approximate foreground any RGB channel differs from127; true gray127 pixels can be lost. All predicted rectangles tightened, same features/naming/track IDs, original geometry policy. No ground truth used to tighten rectangles. Evaluation uses unchanged one-to-one IoU0.5 association.",
            "changed_boxes": sum(
                a["box"] != b["box"]
                for a, b in zip(manifest["rows"], tightened["rows"], strict=True)
            ),
            "stages": {
                key: summarize(tightened, value) for key, value in names.items()
            },
        },
    }
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "original": result["stages"]["none"][
                    "three_observations_with_collision_rejection"
                ],
                "tightened": result["foreground_bounds_control"]["stages"][
                    "three_observations_with_collision_rejection"
                ],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gallery", "queries", "crops", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    diagnose(parser.parse_args())
