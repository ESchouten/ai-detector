"""Cache recognition features from actual detector/tracker boxes.

Ground truth is joined only after image encoding, for evaluation. It never
chooses a crop, supplies a tracking ID, or changes a feature vector.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from recognition_features import adapted_fingerprint, crop_quality
from smoke_runtime import CountedEncoder
from video_assessment import pair_boxes, pixels_hash, read_frame

from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.domain.models import BoundingBox


def collect(args):
    tracking = json.loads(args.tracking.read_text())
    if digest(args.video) != tracking["provenance"]["video"]:
        raise ValueError("Video differs from detector/tracker input")
    base = MiewidEncoder(
        args.cache / "models", device=args.device, weights=args.weights
    )
    if args.adapted_weights:
        from safetensors.torch import load_file

        base.model.load_state_dict(load_file(str(args.adapted_weights)), strict=True)
        base.fingerprint = adapted_fingerprint(base.fingerprint, args.adapted_weights)
    encoder = CountedEncoder(base)
    contract = {
        "version": 1,
        "tracking_sha256": digest(args.tracking),
        "tracking_provenance": tracking["provenance"],
        "encoder_fingerprint": encoder.fingerprint,
        "weights_sha256": digest(args.weights),
        "adapted_weights_sha256": digest(args.adapted_weights)
        if args.adapted_weights
        else None,
        "coordinates": "Truncate XYXY to integers like production; clamp to source dimensions",
        "sample": "Every predicted box at fixed1fps scoring timestamps; actual SDK tracking IDs",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    output_manifest = args.output / "manifest.json"
    if output_manifest.exists():
        previous = json.loads(output_manifest.read_text())
        if previous["contract"] != contract:
            raise ValueError("Output contract changed; choose a new directory")
        if digest(args.output / "vectors.npz") != previous["vectors_sha256"]:
            raise ValueError("Saved vectors changed")
        print(json.dumps({"reused": True, "rows": len(previous["rows"])}))
        return
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    cache = EmbeddingCache(args.cache / "queries.sqlite")
    rows, frames, vectors = [], [], []
    started = time.perf_counter()
    try:
        for frame in tracking["timeline"]:
            source_frame, image = read_frame(capture, frame["second"], fps)
            height, width = image.shape[:2]
            boxes = [
                BoundingBox(
                    max(0, int(box["x1"])),
                    max(0, int(box["y1"])),
                    min(width, int(box["x2"])),
                    min(height, int(box["y2"])),
                    box["label"],
                    box["confidence"],
                    box["track_id"],
                )
                for box in frame["boxes"]
            ]
            coordinates = [[box.x1, box.y1, box.x2, box.y2] for box in boxes]
            crops = [image[y1:y2, x1:x2].copy() for x1, y1, x2, y2 in coordinates]
            if any(not crop.size for crop in crops):
                raise ValueError("Detector produced an empty crop")
            for offset in range(0, len(crops), 8):
                vectors.extend(cache.encode(encoder, crops[offset : offset + 8]))
            # Evaluation-only association: never used to construct the inputs above.
            pairs = pair_boxes(boxes, frame["truth"])
            indices = []
            for index, (box, crop, xyxy) in enumerate(
                zip(boxes, crops, coordinates, strict=True)
            ):
                indices.append(len(rows))
                rows.append(
                    {
                        "second": frame["second"],
                        "frame": source_frame,
                        "track": box.track_id,
                        "box": xyxy,
                        "confidence": box.confidence,
                        "pixels_sha256": pixels_hash(crop),
                        **crop_quality(xyxy, coordinates, width, height),
                        "truth": frame["truth"][pairs[index]]["cow"]
                        if index in pairs
                        else None,
                    }
                )
            frames.append(
                {"second": frame["second"], "rows": indices, "truth": frame["truth"]}
            )
    finally:
        capture.release()
        cache.close()
    np.savez_compressed(
        args.output / "vectors.npz",
        vectors=np.asarray(vectors, dtype=np.float32).reshape(-1, encoder.dimension),
    )
    write_json(
        output_manifest,
        {
            "contract": contract,
            "rows": rows,
            "frames": frames,
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "new_encoded_images": encoder.images,
            "new_encoder_batches": encoder.calls,
            "seconds": time.perf_counter() - started,
        },
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "new_encoded_images": encoder.images,
                "seconds": time.perf_counter() - started,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tracking", "video", "weights", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=Path(".cache/cow-tracked-features")
    )
    parser.add_argument("--device", default="mps")
    parser.add_argument(
        "--adapted-weights",
        type=Path,
        help="Locally trained safetensors state; included in cache fingerprint",
    )
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
