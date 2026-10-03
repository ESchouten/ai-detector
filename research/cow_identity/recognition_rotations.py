"""Gallery-only orientation augmentation; no additional farmer reference labels."""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json
from recognition_experiment import select_gallery


def collect(args):
    from aidetector.adapters.inference.identity import EmbeddingCache
    from aidetector.adapters.inference.miewid import MiewidEncoder

    manifest = json.loads((args.run / "manifest.json").read_text())
    with np.load(args.run / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    selected = sorted(
        set(
            select_gallery(manifest["rows"], vectors, "uniform10").tolist()
            + select_gallery(manifest["rows"], vectors, "diverse10").tolist()
        )
    )
    encoder = MiewidEncoder(
        args.cache / "models", device=args.device, weights=args.weights
    )
    if encoder.fingerprint != manifest["contract"]["encoder_fingerprint"]:
        raise ValueError("Encoder differs from the recorded query cache")
    if digest(args.video) != manifest["contract"]["video_sha256"]:
        raise ValueError("Video differs from the recorded query cache")
    capture = cv2.VideoCapture(str(args.video))
    cache = EmbeddingCache(args.cache / "queries.sqlite")
    rows, result = [], []
    try:
        for i in selected:
            row = manifest["rows"][i]
            capture.set(cv2.CAP_PROP_POS_FRAMES, row["frame"] - 1)
            success, image = capture.read()
            if not success:
                raise ValueError("Enrollment frame cannot be decoded")
            x1, y1, x2, y2 = row["box"]
            crop = image[y1:y2, x1:x2]
            augmented = []
            for flipped in (False, True):
                for quarter_turns in range(4):
                    rotated = np.rot90(
                        crop[:, ::-1] if flipped else crop, quarter_turns
                    ).copy()
                    augmented.append(rotated)
                    rows.append(
                        {"row": i, "quarter_turns": quarter_turns, "flipped": flipped}
                    )
            result.extend(cache.encode(encoder, augmented))
    finally:
        cache.close()
        capture.release()
    np.savez_compressed(args.run / "rotated-gallery.npz", vectors=np.asarray(result))
    write_json(
        args.run / "rotated-gallery.json",
        {
            "manifest_sha256": digest(args.run / "manifest.json"),
            "rows": rows,
            "vectors_sha256": digest(args.run / "rotated-gallery.npz"),
        },
    )
    print(json.dumps({"gallery_images": len(selected), "encoded_variants": len(rows)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=Path(".cache/cow-video-policy-cache")
    )
    parser.add_argument("--device", default="mps")
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
