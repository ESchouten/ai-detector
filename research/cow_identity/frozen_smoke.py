"""Minimal PyInstaller entry point for the actual DINOv2 and MIEWid encoders."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from aidetector.adapters.inference.identity import DinoEncoder
from aidetector.adapters.inference.miewid import MiewidEncoder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    with Image.open(args.crop) as image:
        pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    results = {}
    for name, encoder in (
        ("dino", DinoEncoder(args.cache, device=args.device)),
        ("miewid", MiewidEncoder(args.cache, device=args.device, weights=args.weights)),
    ):
        vectors = encoder.encode([pixels])
        if vectors.shape != (1, encoder.dimension) or not np.isfinite(vectors).all():
            raise AssertionError(f"{name}: invalid frozen inference output")
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-5)
        results[name] = {
            "shape": list(vectors.shape),
            "finite": True,
            "norm": float(np.linalg.norm(vectors[0])),
            "fingerprint": encoder.fingerprint,
        }
    report = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "device": args.device,
        "encoders": results,
        "scope": "Minimal frozen identity entrypoint, not the full application installer",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
