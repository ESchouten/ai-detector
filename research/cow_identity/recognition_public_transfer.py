"""Apply the externally selected cattle metric head to existing feature archives."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_public_head import blend_features, load_head, transform


def apply(head_run, source, output):
    selection = json.loads((head_run / "report.json").read_text())
    selected = selection["selected"]
    if not selected["epoch"]:
        raise ValueError("External validation selected the unchanged baseline")
    weights = head_run / f"head-{selected['epoch']:02d}.safetensors"
    if digest(weights) != selected["weights_sha256"]:
        raise ValueError("Selected head checkpoint changed")
    manifest = json.loads((source / "manifest.json").read_text())
    base = selection["protocol"]["encoder_fingerprint"]
    source_encoder = manifest.get(
        "encoder_fingerprint", manifest["contract"].get("encoder_fingerprint")
    )
    if source_encoder != base:
        raise ValueError(
            "Source encoder differs from the metric-head training features"
        )
    if digest(source / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Source feature archive changed")
    with np.load(source / "vectors.npz", allow_pickle=False) as archive:
        original = archive["vectors"]
    head = load_head(weights)
    transformed = blend_features(
        original, transform(head, original), selected["head_weight"]
    )
    contract = {
        "base": base,
        "head_sha256": selected["weights_sha256"],
        "head_weight": selected["head_weight"],
        "head_architecture": "2152-512-256-v1",
        "torch": torch.__version__,
    }
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / "vectors.npz", vectors=transformed)
    fingerprint = hashlib.sha256(
        json.dumps(contract, sort_keys=True).encode()
    ).hexdigest()
    write_json(
        output / "manifest.json",
        {
            **manifest,
            "encoder_fingerprint": fingerprint,
            "contract": {
                **manifest["contract"],
                "encoder_fingerprint": fingerprint,
                "metric_head": contract,
            },
            "vectors_sha256": digest(output / "vectors.npz"),
            "source_manifest_sha256": digest(source / "manifest.json"),
            "head_selection_sha256": digest(head_run / "report.json"),
            "new_encoded_images": 0,
            "feature_transform_device": "cpu",
        },
    )
    print(
        json.dumps(
            {
                "source": str(source),
                "output": str(output),
                "shape": list(transformed.shape),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--head-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    for source in args.sources:
        apply(args.head_run, source, args.output / source.name)


if __name__ == "__main__":
    main()
