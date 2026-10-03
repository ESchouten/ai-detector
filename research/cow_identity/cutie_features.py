"""Cache appearance evidence from Cutie's predicted masks, without query labels."""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector/src"))

from benchmark import digest, write_json
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components, verified_mask
from smoke_runtime import CountedEncoder
from video_assessment import pixels_hash

from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.miewid import MiewidEncoder


def object_crops(image, mask):
    """Remove disconnected islands and other animals without changing object IDs."""
    cleaned, components = largest_components(mask)
    boxes = boxes_from_mask(cleaned)
    crops = []
    for box in boxes:
        x1, y1, x2, y2 = (box[key] for key in ("x1", "y1", "x2", "y2"))
        selected = cleaned[y1:y2, x1:x2] == box["track_id"] + 1
        crop = np.where(selected[..., None], image[y1:y2, x1:x2], 127)
        crops.append(crop.astype(np.uint8))
    return boxes, crops, components


def load_inputs(args):
    protocol = json.loads(args.protocol.read_text())
    propagation = json.loads(args.propagation.read_text())
    clip = json.loads((args.clip / "sampled.json").read_text())
    if (
        not propagation["complete"]
        or digest(args.propagation) != protocol["propagation_sha256"]
        or digest(args.clip / "sampled.json") != protocol["sampled_manifest_sha256"]
        or digest(args.clip / "sampled.avi") != clip["clip_sha256"]
        or digest(args.weights) != protocol["encoder_weights_sha256"]
    ):
        raise ValueError("Incomplete propagation or frozen input provenance changed")
    seconds = {
        second
        for start, end in protocol["feature_windows"]
        for second in range(start, end + 1)
    }
    if max(seconds) >= 1530:
        raise ValueError("This development control cannot open reserved frames")
    return propagation, clip, seconds


def source_images(directory, clip, seconds):
    capture = cv2.VideoCapture(str(directory / "sampled.avi"))
    try:
        for source in clip["rows"]:
            if not capture.grab():
                raise ValueError("Cached source clip ended prematurely")
            if source["second"] not in seconds:
                continue
            ok, image = capture.retrieve()
            if not ok or pixels_hash(image) != source["pixels_sha256"]:
                raise ValueError("Cached source pixels changed")
            yield int(source["second"]), image
    finally:
        capture.release()


def collect(args):
    import torch

    torch.set_num_threads(2)
    propagation, clip, seconds = load_inputs(args)
    base = MiewidEncoder(args.output / "models", args.device, args.weights)
    encoder = CountedEncoder(base)
    contract = {
        "protocol_sha256": digest(args.protocol),
        "runner_sha256": digest(Path(__file__)),
        "encoder_fingerprint": encoder.fingerprint,
        "crop": "Largest8-connected original object component; original mask AABB; other pixels gray127",
        "box_convention": "Retain the existing frozen Cutie boxes_from_mask convention",
        "labels": "No query ground truth read; original anonymous slots only",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "manifest.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if (
            previous["contract"] != contract
            or digest(args.output / "vectors.npz") != previous["vectors_sha256"]
        ):
            raise ValueError("Existing output differs from this feature contract")
        print(json.dumps({"reused": True, "rows": len(previous["rows"])}))
        return
    cache = EmbeddingCache(args.output / "embeddings.sqlite")
    indexed = {frame["second"]: frame for frame in propagation["timeline"]}
    rows, vectors, frames = [], [], []
    started = time.perf_counter()
    try:
        for second, image in source_images(args.clip, clip, seconds):
            frame = indexed[second]
            mask = verified_mask(args.propagation.parent, frame, image.shape[:2], 8)
            boxes, crops, components = object_crops(image, mask)
            for offset in range(0, len(crops), 8):
                vectors.extend(cache.encode(encoder, crops[offset : offset + 8]))
            frame_rows = []
            statistics = {item["track_id"]: item for item in frame["objects"]}
            for box, crop in zip(boxes, crops, strict=True):
                frame_rows.append(len(rows))
                rows.append(
                    {
                        "second": int(second),
                        "track_id": box["track_id"],
                        "box": [box[key] for key in ("x1", "y1", "x2", "y2")],
                        "mask_sha256": frame["mask_sha256"],
                        "pixels_sha256": pixels_hash(crop),
                        **statistics[box["track_id"]],
                    }
                )
            frames.append(
                {"second": int(second), "rows": frame_rows, "components": components}
            )
            if len(frames) % 50 == 0:
                print(
                    json.dumps(
                        {
                            "frames": len(frames),
                            "rows": len(rows),
                            "seconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
    finally:
        cache.close()
    if {frame["second"] for frame in frames} != seconds:
        raise ValueError("Some requested feature timestamps are missing")
    np.savez_compressed(
        args.output / "vectors.npz", vectors=np.asarray(vectors, dtype=np.float32)
    )
    write_json(
        path,
        {
            "contract": contract,
            "rows": rows,
            "frames": frames,
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "seconds": time.perf_counter() - started,
            "new_encoded_images": encoder.images,
            "new_encoder_batches": encoder.calls,
        },
    )
    print(
        json.dumps(
            {
                "complete": True,
                "rows": len(rows),
                "seconds": time.perf_counter() - started,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "propagation", "clip", "weights", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
