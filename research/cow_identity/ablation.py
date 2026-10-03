"""Exploratory gallery-only covariance control, run entirely from frozen caches.

This condition was added after the first baseline results were inspected. It is
an exploratory ablation, not a new independent confirmation or fitted test policy.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import (
    PROTOCOL,
    cache_key,
    collect_panel,
    digest,
    read_manifest,
    write_json,
)
from scoring import Scores, calibrate, normalize, report, score


def whitening(gallery: np.ndarray, groups: np.ndarray):
    """50% shrinkage within cow/camera; thin SVD avoids a dimension² matrix.

    Only enrollment images fit this transform. No test queries, labels or
    unknown-cow images enter fitting. No dimensionality reduction is performed.
    """
    gallery = normalize(gallery).astype(np.float64)
    residuals = gallery.copy()
    for group in np.unique(groups):
        selected = groups == group
        residuals[selected] -= gallery[selected].mean(axis=0)
    _, singular, basis = np.linalg.svd(residuals, full_matrices=False)
    variance = singular**2 / len(gallery)
    mean_variance = variance.sum() / gallery.shape[1]
    if mean_variance <= 0:
        raise ValueError("Gallery has no within-group variation")
    scale = np.sqrt(mean_variance / (0.5 * variance + 0.5 * mean_variance))

    def apply(values):
        # Directions outside the thin SVD basis retain the ridge inverse scale.
        transformed = (
            np.sqrt(2) * values + ((values @ basis.T) * (scale - np.sqrt(2))) @ basis
        )
        return normalize(transformed)

    return apply


def evaluate(
    manifest: dict, vectors: np.ndarray, adapt: bool, agreement: bool = False
) -> dict:
    results = {}
    for condition in PROTOCOL["conditions"]:
        panels = {}
        for split in ("calibration", "test"):
            gallery, ids, groups, query_groups = collect_panel(
                manifest, vectors, condition, split
            )
            keys = sorted(query_groups)
            query_ids = np.array([key[0] for key in keys])
            cameras = np.array([key[1] for key in keys])
            if adapt:
                transform = whitening(gallery, groups)
                gallery = transform(gallery)
                query_groups = {
                    key: list(transform(np.stack(values)))
                    for key, values in query_groups.items()
                }
            if agreement:
                grouped_scores = []
                for key in keys:
                    query = np.stack(query_groups[key])
                    grouped_scores.append(
                        score(
                            gallery,
                            ids,
                            query,
                            np.full(len(query), key[0]),
                            np.full(len(query), key[1]),
                        )
                    )
                agrees = np.array(
                    [
                        len(set(item.predicted)) == 1 and len(item.predicted) == 3
                        for item in grouped_scores
                    ]
                )
                panels[split] = Scores(
                    query_ids,
                    np.array([item.predicted[0] for item in grouped_scores]),
                    np.where(
                        agrees, [item.similarity.min() for item in grouped_scores], -1
                    ),
                    np.where(
                        agrees, [item.margin.min() for item in grouped_scores], -1
                    ),
                    np.isin(query_ids, ids),
                    cameras,
                )
            else:
                queries = normalize(
                    np.stack([np.mean(query_groups[key], axis=0) for key in keys])
                )
                panels[split] = score(gallery, ids, queries, query_ids, cameras)
        threshold, margin = calibrate(panels["calibration"])
        results[condition] = {
            "calibrated": {
                "threshold": threshold,
                "margin": margin,
                **{
                    split: report(panel, threshold, margin)
                    for split, panel in panels.items()
                },
            },
            "fixed_conservative": {
                "threshold": 0.9,
                "margin": 0.08,
                **{split: report(panel, 0.9, 0.08) for split, panel in panels.items()},
            },
            "fixed_065_010": {
                "threshold": 0.65,
                "margin": 0.10,
                **{split: report(panel, 0.65, 0.10) for split, panel in panels.items()},
            },
            "fixed_065_008": {
                "threshold": 0.65,
                "margin": 0.08,
                **{split: report(panel, 0.65, 0.08) for split, panel in panels.items()},
            },
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--cache", type=Path, default=Path(".cache/cow-identity"))
    args = parser.parse_args()
    manifest = read_manifest(args.run / "manifest.json")
    encoder = json.loads((args.run / "encoder.json").read_text())
    vectors = np.stack(
        [
            np.load(
                args.cache / f"{cache_key(item['sha256'], encoder)}.npy",
                allow_pickle=False,
            )
            for item in manifest["images"]
        ]
    )
    result = {
        "manifest_sha256": manifest["sha256"],
        "encoder": encoder,
        "method": "Fixed 50% within cow/camera gallery covariance shrinkage; no neural fine-tuning",
        "status": "Exploratory: added after raw baseline results were inspected",
        "script_sha256": digest(Path(__file__)),
        "fresh_inferences": 0,
        "raw": evaluate(manifest, vectors, False),
        "adapted": evaluate(manifest, vectors, True),
        "three_sample_agreement_raw": evaluate(manifest, vectors, False, True),
        "three_sample_agreement_adapted": evaluate(manifest, vectors, True, True),
        "agreement_limitation": "Three preselected images; no tracker association or real five-second expiry is evaluated",
    }
    write_json(args.run / "ablation.json", result)
    print(
        json.dumps(
            {
                name: {
                    condition: modes["calibrated"]["test"]["known_coverage"]
                    for condition, modes in result[name].items()
                }
                for name in ("raw", "adapted")
            }
        )
    )


if __name__ == "__main__":
    main()
