"""Encode an independently prepared public-cattle cohort once on MPS."""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json


def collect(args):
    from smoke_runtime import CountedEncoder

    from aidetector.adapters.inference.identity import EmbeddingCache
    from aidetector.adapters.inference.miewid import MiewidEncoder

    cohort = json.loads(args.manifest.read_text())
    encoder = CountedEncoder(
        MiewidEncoder(args.output / "models", device=args.device, weights=args.weights)
    )
    args.output.mkdir(parents=True, exist_ok=True)
    cache = EmbeddingCache(args.output / "features.sqlite")
    vectors = []
    started = time.perf_counter()
    try:
        for start in range(0, len(cohort["rows"]), 8):
            images = []
            for row in cohort["rows"][start : start + 8]:
                path = Path(row["path"])
                if digest(path) != row["sha256"]:
                    raise ValueError(f"Public cohort image changed: {path}")
                with Image.open(path) as image:
                    images.append(np.asarray(image.convert("RGB"))[:, :, ::-1].copy())
            vectors.extend(cache.encode(encoder, images))
            if start % 800 == 0:
                print(
                    json.dumps(
                        {"rows": start, "seconds": time.perf_counter() - started}
                    ),
                    flush=True,
                )
    finally:
        cache.close()
    np.savez_compressed(args.output / "vectors.npz", vectors=np.asarray(vectors))
    write_json(
        args.output / "manifest.json",
        {
            "contract": {
                "cohort_manifest_sha256": digest(args.manifest),
                "cohort": cohort["contract"],
                "encoder_fingerprint": encoder.fingerprint,
                "augmentations": "None; original prepared crops",
            },
            "rows": cohort["rows"],
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "new_encoded_images": encoder.images,
            "seconds": time.perf_counter() - started,
        },
    )
    print(json.dumps({"rows": len(vectors), "seconds": time.perf_counter() - started}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
