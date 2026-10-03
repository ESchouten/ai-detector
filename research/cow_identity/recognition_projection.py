"""Small gallery-only ridge projection and orientation controls, without GPU work."""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_experiment import calibrate_target, pooled_queries, select_gallery
from scoring import Scores, metrics, normalize, score


def ridge(gallery, labels, strength):
    center = gallery.mean(axis=0)
    centered = gallery - center
    classes = np.unique(labels)
    targets = (labels[:, None] == classes[None, :]).astype(float)
    gram = centered @ centered.T
    alpha = strength * np.trace(gram) / len(gallery)
    weights = centered.T @ np.linalg.solve(gram + alpha * np.eye(len(gallery)), targets)

    def predict(queries, truth):
        logits = (queries - center) @ weights
        order = np.argsort(-logits, axis=1, kind="stable")
        predicted = classes[order[:, 0]]
        rows = np.arange(len(queries))
        raw = queries @ gallery.T
        # Preserve native descriptor evidence for open-set rejection. Ridge
        # logits are a discriminative ranking, never advertised as probability.
        similarity = np.array(
            [raw[i, labels == cow].max() for i, cow in enumerate(predicted)]
        )
        margin = logits[rows, order[:, 0]] - logits[rows, order[:, 1]]
        return Scores(
            truth,
            predicted,
            similarity,
            margin,
            np.isin(truth, classes),
            np.zeros(len(truth)),
        )

    return predict


def evaluate(rows, vectors, predictor, pooling):
    panels = {}
    for split in ("development", "development_later", "calibration"):
        positions = [i for i, row in enumerate(rows) if row["panel"] == split]
        selected_rows = [rows[i] for i in positions]
        queries = pooled_queries(selected_rows, vectors[positions], pooling)
        truth = np.array([row["cow"] for row in selected_rows])
        panels[split] = predictor(queries, truth)
    threshold, margin = calibrate_target(panels["calibration"])
    return {
        "threshold": threshold,
        "margin": margin,
        "panels": {
            split: metrics(panel, threshold, margin) for split, panel in panels.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    rows = manifest["rows"]
    with np.load(args.run / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    rotated = json.loads((args.run / "rotated-gallery.json").read_text())
    with np.load(args.run / "rotated-gallery.npz", allow_pickle=False) as archive:
        augmented = normalize(archive["vectors"])
    results = {}
    for method in ("uniform10", "diverse10"):
        selected = select_gallery(rows, vectors, method)
        labels = np.array([rows[i]["cow"] for i in selected])
        for strength in (0.01, 0.1, 1.0, 10.0):
            predictor = ridge(vectors[selected], labels, strength)
            for pooling in (1, 5):
                name = f"{method}-ridge{strength}-pool{pooling}"
                results[name] = evaluate(rows, vectors, predictor, pooling)
        for flipped in (False, True):
            positions = [
                i
                for i, row in enumerate(rotated["rows"])
                if row["row"] in selected and (flipped or not row["flipped"])
            ]
            gallery = augmented[positions]
            owners = np.array(
                [rows[rotated["rows"][i]["row"]]["cow"] for i in positions]
            )

            def predictor(queries, truth, gallery=gallery, owners=owners):
                return score(gallery, owners, queries, truth, np.zeros(len(truth)))

            for pooling in (1, 5):
                name = f"{method}-{'dihedral8' if flipped else 'rotate4'}-pool{pooling}"
                results[name] = evaluate(rows, vectors, predictor, pooling)
    result = {
        "manifest_sha256": digest(args.run / "manifest.json"),
        "status": "Exploratory gallery-only fitting; no final windows",
        "conditions": results,
    }
    write_json(args.run / "projection.json", result)
    for name, condition in results.items():
        print(
            name,
            json.dumps(
                {
                    split: [
                        round(value[key], 4) if value[key] is not None else None
                        for key in (
                            "accepted_precision",
                            "known_coverage",
                            "unknown_false_acceptance_rate",
                            "known_rank1",
                        )
                    ]
                    for split, value in condition["panels"].items()
                }
            ),
        )


if __name__ == "__main__":
    main()
