"""Frozen full-frame passage control using the application's identity policy."""

import argparse
import json
import tarfile
import time
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from smoke_runtime import CountedEncoder
from video_assessment import pixels_hash

from aidetector.adapters.inference.device import mps_inference
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.adapters.inference.yolo import map_observations
from aidetector.adapters.media.images import shrink_image
from aidetector.domain.models import Frame

HERE = Path(__file__).parent
PROTOCOL = HERE / "passage_protocol.json"
MANIFEST = HERE / "results/2026-10-03/purdue-passage-manifest.json"
LABELS = HERE / "results/2026-10-03/purdue-passage-labels.json"


def frozen_inputs(path=PROTOCOL):
    protocol = json.loads(path.read_text())
    if (
        digest(MANIFEST) != protocol["manifest_sha256"]
        or digest(LABELS) != protocol["principal_labels_sha256"]
    ):
        raise ValueError("Passage source manifest or principal labels changed")
    for path, expected in protocol["source_hashes"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen runtime changed: {path}")
    if digest(Path(protocol["detector"]["model"])) != protocol["detector"]["sha256"]:
        raise ValueError("Frozen passage detector weights changed")
    return protocol, json.loads(MANIFEST.read_text())


def materialize(clip, directory):
    destination = directory / clip["clip"] / "source.avi"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        archive = Path(clip["archive"])
        if digest(archive) != clip["archive_sha256"]:
            raise ValueError("Source passage archive changed")
        with tarfile.open(archive) as source:
            member = source.getmember(clip["member"])
            if not member.isfile():
                raise ValueError("Passage member is not an ordinary file")
            with source.extractfile(member) as stream:
                destination.write_bytes(stream.read())
    if digest(destination) != clip["sha256"]:
        raise ValueError("Source passage clip changed")
    return destination


def sampled_frames(clip, path, width):
    capture = cv2.VideoCapture(str(path))
    expected = iter(clip["sampled_local_frame_indices"])
    target = next(expected, None)
    frame_index = 0
    try:
        while target is not None:
            ok, image = capture.read()
            if not ok:
                raise ValueError("Passage ended before all frozen sample frames")
            if frame_index == target:
                if image.shape[:2] != (clip["height"], clip["width"]):
                    raise ValueError("Decoded passage dimensions differ from manifest")
                yield frame_index, shrink_image(image, width)
                target = next(expected, None)
            frame_index += 1
    finally:
        capture.release()


def detector_observations(clip, source, protocol, device="mps"):
    from ultralytics import YOLO

    settings = protocol["detector"]
    model = YOLO(settings["model"])
    classes = settings.get(
        "class_ids",
        [key for key, label in model.names.items() if label in settings["classes"]],
    )
    if not classes:
        raise ValueError("Frozen class names do not select a detector class")
    labels = (
        settings["classes"]
        if "class_ids" in settings
        else [model.names[key] for key in classes]
    )
    mapping = {
        key: (label, settings["confidence"])
        for key, label in zip(classes, labels, strict=True)
    }
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    sampling = clip
    if "processing_fps" in protocol:
        stride = (
            clip["fps_numerator"] / clip["fps_denominator"] / protocol["processing_fps"]
        )
        if not stride.is_integer():
            raise ValueError("Passage processing cadence must divide source FPS")
        sampling = {
            **clip,
            "sampled_local_frame_indices": list(range(0, clip["frames"], int(stride))),
        }
    for index, image in sampled_frames(sampling, source, settings["frames_width"]):
        second = index * clip["fps_denominator"] / clip["fps_numerator"]
        at = epoch + timedelta(seconds=second)
        with mps_inference() if device == "mps" else nullcontext():
            result = model.track(
                image,
                persist=True,
                tracker=settings["tracker"],
                device=device,
                classes=classes,
                conf=settings["confidence"],
                imgsz=settings["imgsz"],
                quantize=settings.get("quantize", 16),
                verbose=False,
            )[0]
            observation = map_observations(result, (Frame(at, image),), mapping)[0]
        yield index, second, observation


def enroll_proposals(args):
    import torch

    torch.set_num_threads(2)
    protocol, manifest = frozen_inputs(args.protocol)
    if (args.output / "proposals.json").exists():
        raise ValueError(
            "Enrollment proposals already exist; preserve their review provenance"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    encoder = CountedEncoder(
        MiewidEncoder(args.output / "models", args.device, weights=args.weights)
    )
    cache = EmbeddingCache(args.output / "embeddings.sqlite")
    rows, frames, vectors = [], [], []
    try:
        for clip in manifest["clips"]:
            if clip["role"] != "enrollment":
                continue
            source = materialize(clip, args.output / "clips")
            for index, second, observation in detector_observations(
                clip, source, protocol, args.device
            ):
                height, width = observation.image.shape[:2]
                indices = []
                for box in observation.boxes:
                    row_index = len(rows)
                    crop = observation.image[box.y1 : box.y2, box.x1 : box.x2].copy()
                    if not crop.size:
                        raise ValueError("Detector produced an empty passage crop")
                    filename = f"crops/{row_index:04d}.png"
                    (args.output / "crops").mkdir(exist_ok=True)
                    cv2.imwrite(str(args.output / filename), crop)
                    vectors.extend(cache.encode(encoder, [crop]))
                    policy = protocol["identity_policy"]
                    rows.append(
                        {
                            "clip": clip["clip"],
                            "local_frame": index,
                            "second": second,
                            "frame_width": width,
                            "frame_height": height,
                            "box": asdict(box),
                            "path": filename,
                            "pixels_sha256": pixels_hash(crop),
                            "eligible": usable_crop(
                                box,
                                observation.boxes,
                                width,
                                height,
                                policy["min_crop_size"],
                                policy["max_overlap"],
                            ),
                        }
                    )
                    indices.append(row_index)
                frame_path = f"clips/{clip['clip']}/frame-{index:06d}.png"
                cv2.imwrite(str(args.output / frame_path), observation.image)
                frames.append(
                    {
                        "clip": clip["clip"],
                        "local_frame": index,
                        "second": second,
                        "path": frame_path,
                        "pixels_sha256": pixels_hash(observation.image),
                        "rows": indices,
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
            "encoder_fingerprint": encoder.fingerprint,
            "device": args.device,
            "manifest_sha256": digest(MANIFEST),
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "frames": frames,
            "rows": rows,
            "new_encoded_crops": encoder.images,
            "seconds": time.perf_counter() - started,
            "status": "June8 enrollment proposals only; principal identity not assigned without human review; no query images read",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enrollment-proposals")
    enroll.add_argument("--weights", type=Path, required=True)
    enroll.add_argument("--output", type=Path, required=True)
    enroll.add_argument("--protocol", type=Path, default=PROTOCOL)
    enroll.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args()
    enroll_proposals(args)


if __name__ == "__main__":
    main()
