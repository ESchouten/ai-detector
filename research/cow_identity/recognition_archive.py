"""Encode a verified existing crop archive with a research encoder checkpoint."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from recognition_features import make_encoder


def encode(args):
    from aidetector.adapters.inference.identity import EmbeddingCache

    manifest = json.loads((args.source / "manifest.json").read_text())
    encoder = make_encoder(args)
    source_hash = digest(args.source / "manifest.json")
    args.output.mkdir(parents=True, exist_ok=True)
    existing = args.output / "manifest.json"
    if existing.exists():
        previous = json.loads(existing.read_text())
        if (
            previous["encoder_fingerprint"] != encoder.fingerprint
            or previous["source_manifest_sha256"] != source_hash
            or digest(args.output / "vectors.npz") != previous["vectors_sha256"]
        ):
            raise ValueError("Output contract changed; use a new directory")
        print(json.dumps({"reused": True, "rows": len(previous["rows"])}))
        return
    cache = EmbeddingCache(args.cache / "queries.sqlite")
    vectors = []
    started = time.perf_counter()
    try:
        for start in range(0, len(manifest["rows"]), 8):
            images = []
            for row in manifest["rows"][start : start + 8]:
                path = Path(row["pixels_path"])
                if digest(path) != row["sha256"]:
                    raise ValueError(f"Archived crop changed: {path}")
                images.append(cv2.imread(str(path)))
            vectors.extend(cache.encode(encoder, images))
    finally:
        cache.close()
    np.savez_compressed(args.output / "vectors.npz", vectors=np.asarray(vectors))
    manifest.update(
        contract={**manifest["contract"], "encoder_fingerprint": encoder.fingerprint},
        encoder_fingerprint=encoder.fingerprint,
        source_manifest_sha256=source_hash,
        device=args.device,
        vectors_sha256=digest(args.output / "vectors.npz"),
        new_encoded_images=encoder.images,
        inference_seconds=time.perf_counter() - started,
    )
    write_json(args.output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in ("device", "new_encoded_images", "inference_seconds")
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--adapted-weights", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=Path(".cache/cow-video-policy-cache")
    )
    parser.add_argument("--device", default="mps")
    parser.add_argument(
        "--encoder", choices=("miewid", "megab", "megab-stretch"), default="miewid"
    )
    encode(parser.parse_args())


if __name__ == "__main__":
    main()
