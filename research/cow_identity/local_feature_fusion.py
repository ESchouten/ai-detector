"""Evaluate cached local/global score fusion without opening final-test data."""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from scoring import Scores, metrics


def calibrate_fusion(scores, upper):
    candidates = []
    for threshold in np.arange(0.2, upper + 0.02, 0.01):
        for margin in np.arange(0.02, 0.52, 0.02):
            accepted = (scores.similarity >= threshold) & (scores.margin >= margin)
            correct = accepted & (scores.predicted == scores.truth) & scores.known
            count = int(accepted.sum())
            if (
                count
                and correct.sum() / count >= 0.99
                and (accepted & ~scores.known).sum() / (~scores.known).sum() <= 0.01
            ):
                candidates.append((int(correct.sum()), float(threshold), float(margin)))
    return max(candidates, default=(0, upper + 1, 1))


def subset(scores, mask):
    return Scores(
        *(getattr(scores, name)[mask] for name in Scores.__dataclass_fields__)
    )


def evaluate(features, local, score_field="scores"):
    manifest_path = features / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    local_manifest = json.loads((local / "manifest.json").read_text())
    if digest(manifest_path) != local_manifest["input_manifest_sha256"]:
        raise ValueError("Feature manifests differ")
    if digest(local / "scores.npz") != local_manifest["scores_sha256"]:
        raise ValueError("Local score array changed")
    if digest(features / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Global feature array changed")
    with np.load(local / "scores.npz", allow_pickle=False) as arrays:
        queries, gallery, local_scores = (
            arrays["queries"],
            arrays["gallery"],
            arrays[score_field],
        )
    with np.load(features / "vectors.npz", allow_pickle=False) as arrays:
        vectors = arrays["vectors"]
    rows = manifest["rows"]
    owners = np.array([rows[i]["cow"] for i in gallery])
    truth = np.array([rows[i]["cow"] for i in queries])
    panels = np.array([rows[i]["panel"] for i in queries])
    global_scores = vectors[queries] @ vectors[gallery].T
    local_scores = np.log1p(local_scores) / np.log(33)
    variants = []
    for weight in (0, 0.05, 0.1, 0.2, 0.3, 0.5, 1):
        fused = global_scores + weight * local_scores
        by_identity = np.stack(
            [fused[:, owners == cow].max(axis=1) for cow in range(1, 7)], axis=1
        )
        order = np.argsort(-by_identity, axis=1, kind="stable")
        index = np.arange(len(queries))
        best = by_identity[index, order[:, 0]]
        scores = Scores(
            truth,
            order[:, 0] + 1,
            best,
            best - by_identity[index, order[:, 1]],
            truth <= 6,
            panels,
        )
        hits, threshold, margin = calibrate_fusion(
            subset(scores, panels == "calibration"), 1 + weight
        )
        variants.append(
            {
                "local_weight": weight,
                "calibration_choice": [hits, threshold, margin],
                "panels": {
                    panel: metrics(subset(scores, panels == panel), threshold, margin)
                    for panel in ("development", "development_later", "calibration")
                },
            }
        )
    return {
        "method": local_manifest["contract"],
        "input_manifest_sha256": digest(manifest_path),
        "score_array_sha256": local_manifest["scores_sha256"],
        "score_field": score_field,
        "gallery": gallery.tolist(),
        "query_seconds": {
            panel: sorted(
                {rows[i]["second"] for i in queries if rows[i]["panel"] == panel}
            )
            for panel in sorted(set(panels))
        },
        "sampling": "Oracle development/calibration crops; no temporal pooling; final windows unopened",
        "selection": "Per-weight threshold/margin grid on calibration only: maximize correct, precision>=.99, unknownFA<=.01; all weights reported",
        "timing_seconds": local_manifest["total_seconds"],
        "variants": variants,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--score-field", choices=("scores", "raw_scores"), default="scores"
    )
    args = parser.parse_args()
    write_json(args.output, evaluate(args.features, args.local, args.score_field))


if __name__ == "__main__":
    main()
