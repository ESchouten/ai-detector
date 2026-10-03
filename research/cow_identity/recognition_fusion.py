"""Fixed equal-weight descriptor fusion from two verified feature archives."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_compare import load
from scoring import normalize


def observation_key(row):
    """Use the observed photo and track, never its evaluation identity."""
    return (
        row["frame"],
        row["second"],
        tuple(row["box"]),
        row.get("track"),
        row["pixels_sha256"],
    )


def align_observations(left, right):
    positions = {observation_key(row): i for i, row in enumerate(left["rows"])}
    if len(positions) != len(left["rows"]):
        raise ValueError("Original archive contains duplicate observations")
    right_positions = {}
    for index, row in enumerate(right["rows"]):
        key = observation_key(row)
        if key in right_positions or key not in positions:
            raise ValueError("Transformed observations are duplicated or changed")
        if row.get("source_row", positions[key]) != positions[key]:
            raise ValueError("Transformed source-row index disagrees with its photo")
        right_positions[key] = index
    if "frames" in left and len(right_positions) != len(positions):
        raise ValueError("Tracked fusion must retain every predicted box")
    selected = [i for key, i in positions.items() if key in right_positions]
    aligned = [right_positions[observation_key(left["rows"][i])] for i in selected]
    return selected, aligned


def representation(contract):
    return contract.get("representation_fingerprint", contract["encoder_fingerprint"])


def fusion_contract(left, right):
    return {
        "version": 2,
        "method": "Equal-weight cosine via normalized concatenation of two unit descriptors",
        "left_representation": representation(left["contract"]),
        "right_representation": representation(right["contract"]),
        "numpy": np.__version__,
    }


def fuse(args):
    left, left_vectors = load(args.original)
    right, right_vectors = load(args.transformed)
    source_hash = digest(args.original / "manifest.json")
    if right["contract"].get("source_manifest_sha256") != source_hash:
        raise ValueError("Transformed archive does not link to this exact source")
    if len(left_vectors) != len(left["rows"]) or len(right_vectors) != len(
        right["rows"]
    ):
        raise ValueError("Vector and observation counts differ")
    positions, aligned = align_observations(left, right)
    rows = [left["rows"][i] for i in positions]
    vectors = normalize(
        np.concatenate([left_vectors[positions], right_vectors[aligned]], axis=1)
    )
    fusion = fusion_contract(left, right)
    fingerprint = hashlib.sha256(
        json.dumps(fusion, sort_keys=True).encode()
    ).hexdigest()
    contract = {
        **left["contract"],
        "encoder_fingerprint": fingerprint,
        "representation_fingerprint": fingerprint,
        "representation": fusion,
        "fusion_sources": {
            "left_manifest_sha256": source_hash,
            "right_manifest_sha256": digest(args.transformed / "manifest.json"),
        },
    }
    if "panels" in contract:
        contract["panels"] = {
            name: sorted({row["second"] for row in rows if row["panel"] == name})
            for name in {row["panel"] for row in rows}
        }
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output / "vectors.npz", vectors=vectors)
    write_json(
        args.output / "manifest.json",
        {
            "contract": contract,
            "rows": rows,
            **({"frames": left["frames"]} if "frames" in left else {}),
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "new_encoded_images": 0,
            "feature_transform_device": "cpu",
        },
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "dimension": vectors.shape[1],
                "encoder_fingerprint": fingerprint,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("transformed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    fuse(parser.parse_args())


if __name__ == "__main__":
    main()
