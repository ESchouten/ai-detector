"""Collect first-day enrollment proposals using separately detected coat torsos."""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_runtime import MANIFEST, frozen_inputs, materialize
from passage_torso import associate_torsos
from passage_torso_detection import observations
from smoke_runtime import CountedEncoder
from video_assessment import pixels_hash

from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.adapters.inference.miewid import MiewidEncoder


def retain_proposals(
    observation, clip, index, second, output, cache, encoder, rows, vectors
):
    whole = tuple(b for b in observation.boxes if b.label == "whole_visible_cow")
    torsos = tuple(b for b in observation.boxes if b.label == "coat_torso")
    pairs = associate_torsos(whole, torsos)
    paired_torsos = tuple(torso for _, torso in pairs)
    height, width = observation.image.shape[:2]
    indices = []
    for owner, torso in pairs:
        crop = observation.image[torso.y1 : torso.y2, torso.x1 : torso.x2].copy()
        row_index = len(rows)
        filename = f"crops/{row_index:04d}.png"
        if not cv2.imwrite(str(output / filename), crop):
            raise OSError("Could not retain proposed torso pixels")
        vectors.extend(cache.encode(encoder, [crop]))
        rows.append(
            {
                "clip": clip["clip"],
                "local_frame": index,
                "second": second,
                "frame_width": width,
                "frame_height": height,
                "box": asdict(torso),
                "whole_box": asdict(whole[owner]),
                "path": filename,
                "pixels_sha256": pixels_hash(crop),
                "eligible": usable_crop(torso, paired_torsos, width, height, 64, 0.2),
            }
        )
        indices.append(row_index)
    return {
        "clip": clip["clip"],
        "local_frame": index,
        "second": second,
        "rows": indices,
        "whole_boxes": [asdict(b) for b in whole],
        "torso_boxes": [asdict(b) for b in torsos],
        "unassociated_torsos": len(torsos) - len(pairs),
    }


def enroll(args):
    import torch

    torch.set_num_threads(2)
    protocol, manifest = frozen_inputs(args.protocol)
    if args.output.exists():
        raise ValueError("Preserve earlier enrollment proposals")
    (args.output / "crops").mkdir(parents=True)
    started = time.perf_counter()
    encoder = CountedEncoder(
        MiewidEncoder(args.output / "models", "mps", weights=args.weights)
    )
    cache = EmbeddingCache(args.output / "embeddings.sqlite")
    rows, frames, vectors = [], [], []
    try:
        for clip in manifest["clips"]:
            if clip["role"] != "enrollment":
                continue
            source = materialize(clip, args.output / "clips")
            for index, second, observation in observations(clip, source, protocol):
                frame = retain_proposals(
                    observation,
                    clip,
                    index,
                    second,
                    args.output,
                    cache,
                    encoder,
                    rows,
                    vectors,
                )
                filename = f"clips/{clip['clip']}/frame-{index:06d}.png"
                cv2.imwrite(str(args.output / filename), observation.image)
                frames.append(
                    {
                        **frame,
                        "path": filename,
                        "pixels_sha256": pixels_hash(observation.image),
                    }
                )
    finally:
        cache.close()
    np.savez_compressed(
        args.output / "vectors.npz",
        vectors=np.array(vectors, dtype=np.float32).reshape(-1, encoder.dimension),
    )
    write_json(
        args.output / "proposals.json",
        {
            "protocol_sha256": digest(args.protocol),
            "script_sha256": digest(Path(__file__)),
            "association_source_sha256": digest(
                Path(__file__).with_name("passage_torso.py")
            ),
            "encoder_fingerprint": encoder.fingerprint,
            "device": "mps",
            "manifest_sha256": digest(MANIFEST),
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "frames": frames,
            "rows": rows,
            "new_encoded_crops": encoder.images,
            "seconds": time.perf_counter() - started,
            "status": "June8 predicted torso proposals; no automatic biological labels, independent review required",
        },
    )
    print(
        json.dumps(
            {
                "frames": len(frames),
                "proposals": len(rows),
                "eligible": sum(row["eligible"] for row in rows),
                "seconds": time.perf_counter() - started,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("protocol", "weights", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    enroll(parser.parse_args())
