"""Compare encoder archives on exactly the same sparse video observations.

The two primary controls use the same reference photos. An additional control
lets each encoder select its own diverse references from early enrollment only.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_experiment import select_gallery
from recognition_projection import evaluate
from scoring import normalize, score


def row_key(row):
    return row["panel"], row["cow"], row["second"]


def load(run):
    manifest = json.loads((run / "manifest.json").read_text())
    if digest(run / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError(f"Feature archive changed: {run}")
    with np.load(run / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    return manifest, vectors


def verify_source(baseline, baseline_manifest, candidate_manifest):
    candidate_contract = candidate_manifest["contract"]
    if "video_sha256" in candidate_contract:
        same_source = (
            baseline_manifest["contract"]["video_sha256"]
            == candidate_contract["video_sha256"]
        )
    else:
        # Crop transforms retain the complete, hashed source manifest instead
        # of duplicating its video metadata. Verify that link to the baseline.
        same_source = candidate_contract.get("source_manifest_sha256") == digest(
            baseline / "manifest.json"
        )
    if not same_source:
        raise ValueError("Candidate provenance does not link to the baseline video")


def compare(baseline, candidate):
    baseline_manifest, baseline_vectors = load(baseline)
    candidate_manifest, candidate_vectors = load(candidate)
    verify_source(baseline, baseline_manifest, candidate_manifest)
    shared = {row_key(row) for row in candidate_manifest["rows"]} & {
        row_key(row) for row in baseline_manifest["rows"]
    }
    reference_photos = {
        method: [
            row_key(baseline_manifest["rows"][i])
            for i in select_gallery(baseline_manifest["rows"], baseline_vectors, method)
        ]
        for method in ("uniform10", "diverse10")
    }
    result = {
        "scope": "Single-image oracle comparison on common rows; no temporal-policy or final-test claim",
        "threshold_selection": "Each condition uses calibration only, target99%precision/1%unknownFA",
        "shared_rows": len(shared),
        "reference_photos": reference_photos,
        "models": {},
    }
    for name, path, manifest, vectors in (
        ("baseline", baseline, baseline_manifest, baseline_vectors),
        ("candidate", candidate, candidate_manifest, candidate_vectors),
    ):
        positions = [
            i for i, row in enumerate(manifest["rows"]) if row_key(row) in shared
        ]
        rows = [manifest["rows"][i] for i in positions]
        vectors = vectors[positions]
        lookup = {row_key(row): i for i, row in enumerate(rows)}
        galleries = {
            method: np.array([lookup[key] for key in keys])
            for method, keys in reference_photos.items()
        }
        galleries["own_diverse10"] = select_gallery(rows, vectors, "diverse10")
        conditions = {}
        for method, selected in galleries.items():
            gallery = vectors[selected]
            labels = np.array([rows[i]["cow"] for i in selected])

            def predict(queries, truth, gallery=gallery, labels=labels):
                return score(gallery, labels, queries, truth, np.zeros(len(truth)))

            conditions[method] = evaluate(rows, vectors, predict, 1)
        result["models"][name] = {
            "manifest_sha256": digest(path / "manifest.json"),
            "encoder_fingerprint": manifest["contract"]["encoder_fingerprint"],
            "conditions": conditions,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.baseline, args.candidate)
    write_json(args.output, result)
    print(json.dumps(result["models"], indent=2))


if __name__ == "__main__":
    main()
