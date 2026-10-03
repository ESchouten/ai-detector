"""Freeze exactly60 early confirmed masked photos for a farm-adaptation pilot."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_compare import load
from recognition_experiment import select_gallery
from recognition_fusion import observation_key


def validate_rows(rows):
    if Counter(row["cow"] for row in rows) != {cow: 10 for cow in range(1, 7)}:
        raise ValueError(
            "Farm training requires exactly10 confirmed photos for each known cow"
        )
    seen = set()
    for row in rows:
        key = observation_key(row)
        if (
            key in seen
            or row["panel"] != "enrollment"
            or not 0 <= row["second"] <= 299
            or row["frame"] != row["second"] * 20 + 1
        ):
            raise ValueError(
                "Only distinct early enrollment photos may train the farm model"
            )
        if row["identity"] != f"8calves-confirmed:{row['cow']}":
            raise ValueError("Farm identity differs from its confirmed reference")
        seen.add(key)


def prepare(args):
    original, original_vectors = load(args.original)
    masked, masked_vectors = load(args.masked)
    crops = json.loads((args.crops / "crops.json").read_text())
    original_hash = digest(args.original / "manifest.json")
    if any(
        contract["source_manifest_sha256"] != original_hash
        for contract in (masked["contract"], crops["contract"])
    ):
        raise ValueError("Masked features and photos must link to the original gallery")
    positions = {observation_key(row): i for i, row in enumerate(masked["rows"])}
    crop_rows = {observation_key(row): row for row in crops["rows"]}
    rows, selected = [], []
    for index in select_gallery(original["rows"], original_vectors, "diverse10"):
        row = original["rows"][index]
        key = observation_key(row)
        candidate = crop_rows[key]["variants"]["masked"]
        if masked["rows"][positions[key]]["variants"]["masked"] != candidate:
            raise ValueError("Masked photo differs from its encoded feature")
        path = args.crops / candidate["path"]
        rows.append(
            {
                **row,
                "identity": f"8calves-confirmed:{row['cow']}",
                "dataset": "enrollment",
                "split": "train",
                "day": row["second"],
                "path": str(path),
                "sha256": digest(path),
                "masked_pixels_sha256": candidate["pixels_sha256"],
            }
        )
        selected.append(positions[key])
    validate_rows(rows)
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output / "vectors.npz", vectors=masked_vectors[selected])
    write_json(
        args.output / "manifest.json",
        {
            "contract": {
                "scope": "Same60original confirmed early references, SAM foreground-only; no later or unknown photos",
                "original_manifest_sha256": original_hash,
                "masked_manifest_sha256": digest(args.masked / "manifest.json"),
                "crops_manifest_sha256": digest(args.crops / "crops.json"),
                "base_encoder_fingerprint": masked["contract"]["representation"][
                    "encoder_fingerprint"
                ],
                "representation": masked["contract"]["representation"],
                "representation_fingerprint": masked["contract"][
                    "representation_fingerprint"
                ],
            },
            "rows": rows,
            "vectors_sha256": digest(args.output / "vectors.npz"),
        },
    )
    print(
        json.dumps(
            {
                "training_photos": len(rows),
                "identities": len({row["cow"] for row in rows}),
            }
        )
    )


def load_training(path):
    manifest, vectors = load(path)
    validate_rows(manifest["rows"])
    for row in manifest["rows"]:
        if digest(Path(row["path"])) != row["sha256"]:
            raise ValueError("Confirmed farm training photo changed")
    return manifest, vectors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "masked", "crops", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
