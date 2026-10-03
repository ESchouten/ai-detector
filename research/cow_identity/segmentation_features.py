"""Cache foreground-only crops for a bounded recognition diagnostic.

SAM receives only pixels and box prompts. Publisher identities remain evaluation
labels. Existing recognition manifests exclude the reserved final windows.
"""

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash, read_frame


def aligned_crop(image, mask):
    """Rotate the mask's principal axis vertically; retain its 180° ambiguity."""
    points = np.column_stack(np.nonzero(mask)[::-1]).astype(np.float32)
    if len(points) < 3:
        return image.copy()
    center, axes = cv2.PCACompute(points, mean=None)
    angle = np.degrees(np.arctan2(axes[0, 1], axes[0, 0])) - 90
    matrix = cv2.getRotationMatrix2D(tuple(center[0]), float(angle), 1)
    height, width = image.shape[:2]
    side = int(np.ceil(np.hypot(width, height)))
    matrix[:, 2] += (side / 2 - center[0, 0], side / 2 - center[0, 1])
    rotated = cv2.warpAffine(image, matrix, (side, side), borderValue=(127, 127, 127))
    rotated_mask = cv2.warpAffine(
        mask.astype(np.uint8), matrix, (side, side), flags=cv2.INTER_NEAREST
    )
    x, y, width, height = cv2.boundingRect(rotated_mask)
    return rotated[y : y + height, x : x + width].copy()


def save_crops(items, masks, image, directory):
    rows = []
    for (index, row), mask in zip(items, masks, strict=True):
        x1, y1, x2, y2 = row["box"]
        crop = image[y1:y2, x1:x2].copy()
        if pixels_hash(crop) != row["pixels_sha256"]:
            raise ValueError("Cropped pixels differ from original experiment")
        foreground = mask[y1:y2, x1:x2]
        isolated = np.where(foreground[..., None], crop, 127).astype(np.uint8)
        variants = {
            "masked": isolated,
            "aligned": aligned_crop(isolated, foreground),
        }
        paths = {}
        for variant, value in variants.items():
            filename = f"{index}-{variant}.png"
            cv2.imwrite(str(directory / filename), value)
            paths[variant] = {
                "path": f"crops/{filename}",
                "pixels_sha256": pixels_hash(value),
            }
        rows.append(
            {**row, "mask_fraction": float(foreground.mean()), "variants": paths}
        )
    return rows


def prepare(args):
    import torch
    from ultralytics import SAM

    torch.set_num_threads(2)
    original = json.loads((args.source / "manifest.json").read_text())
    tracked = "frames" in original
    video_hash = (
        original["contract"]["tracking_provenance"]["video"]
        if tracked
        else original["contract"]["video_sha256"]
    )
    if digest(args.video) != video_hash:
        raise ValueError("Source video differs from the recognition manifest")
    chosen = [
        {**row, "source_row": index} if tracked else row
        for index, row in enumerate(original["rows"])
        if row.get("panel") == "enrollment" or row["second"] % args.stride == 0
    ]
    if any(row["second"] >= 1530 for row in chosen):
        raise ValueError("Reserved final frames are not part of this diagnostic")
    by_frame = defaultdict(list)
    for index, row in enumerate(chosen):
        by_frame[row["second"]].append((index, row))
    model = SAM(str(args.sam))
    contract = {
        "version": 1,
        "source_manifest_sha256": digest(args.source / "manifest.json"),
        "sam_sha256": digest(args.sam),
        "sam_imgsz": 1024,
        "sam_device": args.device,
        "ultralytics": __import__("ultralytics").__version__,
        "stride": args.stride,
        "background": 127,
        "alignment": "mask principal axis vertical, no directed head cue",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    contract_path = args.output / "crop-contract.json"
    if contract_path.exists() and json.loads(contract_path.read_text()) != contract:
        raise ValueError("Crop contract changed; use a new output directory")
    write_json(contract_path, contract)
    crops = args.output / "crops"
    crops.mkdir(exist_ok=True)
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    result_rows = []
    started = time.perf_counter()
    try:
        for count, (second, items) in enumerate(by_frame.items()):
            metadata_path = crops / f"{second}.json"
            if metadata_path.exists():
                result_rows.extend(json.loads(metadata_path.read_text()))
                continue
            _, image = read_frame(capture, second, fps)
            result = model.predict(
                image,
                bboxes=[row["box"] for _, row in items],
                device=args.device,
                imgsz=1024,
                verbose=False,
            )[0]
            masks = result.masks.data.cpu().numpy() > 0.5
            if masks.shape != (len(items), *image.shape[:2]):
                raise ValueError(f"Unexpected SAM mask dimensions: {masks.shape}")
            frame_rows = save_crops(items, masks, image, crops)
            write_json(metadata_path, frame_rows)
            result_rows.extend(frame_rows)
            if count % 20 == 0:
                print(
                    json.dumps(
                        {"frames": count + 1, "seconds": time.perf_counter() - started}
                    ),
                    flush=True,
                )
    finally:
        capture.release()
    result = {
        "contract": contract,
        "origin": original["contract"],
        "rows": result_rows,
        "seconds": time.perf_counter() - started,
    }
    if tracked:
        positions = {row["source_row"]: i for i, row in enumerate(result_rows)}
        result["tracking_provenance"] = original["contract"]["tracking_provenance"]
        result["frames"] = [
            {**frame, "rows": [positions[i] for i in frame["rows"]]}
            for frame in original["frames"]
            if frame["second"] % args.stride == 0
        ]
    write_json(args.output / "crops.json", result)


def encode(args):
    from smoke_runtime import CountedEncoder

    from aidetector.adapters.inference.identity import EmbeddingCache
    from aidetector.adapters.inference.miewid import MiewidEncoder

    crops = json.loads((args.source / "crops.json").read_text())
    origin = crops.get("origin")
    if args.source_manifest is not None:
        if digest(args.source_manifest) != crops["contract"]["source_manifest_sha256"]:
            raise ValueError("Original manifest differs from the crop provenance")
        origin = json.loads(args.source_manifest.read_text())["contract"]
    base_encoder = MiewidEncoder(
        args.output / "models", device=args.device, weights=args.weights
    )
    if args.adapted_weights is not None:
        from recognition_features import adapted_fingerprint
        from safetensors.torch import load_file

        base_encoder.model.load_state_dict(
            load_file(str(args.adapted_weights)), strict=True
        )
        base_encoder.fingerprint = adapted_fingerprint(
            base_encoder.fingerprint, args.adapted_weights
        )
    encoder = CountedEncoder(base_encoder)
    representation = {
        "encoder_fingerprint": encoder.fingerprint,
        "variant": args.variant,
        **{
            key: crops["contract"][key]
            for key in (
                "sam_sha256",
                "sam_imgsz",
                "sam_device",
                "ultralytics",
                "background",
                "alignment",
            )
        },
    }
    contract = {
        **crops["contract"],
        "encoder_fingerprint": encoder.fingerprint,
        "variant": args.variant,
    }
    encoder.fingerprint = hashlib.sha256(
        json.dumps(contract, sort_keys=True).encode()
    ).hexdigest()
    contract["encoder_fingerprint"] = encoder.fingerprint
    # Existing inference-cache keys stay intact. The representation contract
    # omits dataset provenance so separate gallery/query archives can be compared.
    contract["representation"] = representation
    contract["representation_fingerprint"] = hashlib.sha256(
        json.dumps(representation, sort_keys=True).encode()
    ).hexdigest()
    if "tracking_provenance" in crops:
        contract["tracking_provenance"] = crops["tracking_provenance"]
    if origin is not None:
        contract["origin"] = origin
    args.output.mkdir(parents=True, exist_ok=True)
    cache = EmbeddingCache(args.source / "masked-embeddings.sqlite")
    vectors = []
    started = time.perf_counter()
    try:
        for start in range(0, len(crops["rows"]), 8):
            rows = crops["rows"][start : start + 8]
            images = []
            for row in rows:
                variant = row["variants"][args.variant]
                image = cv2.imread(str(args.source / variant["path"]))
                if pixels_hash(image) != variant["pixels_sha256"]:
                    raise ValueError("Prepared crop pixels changed")
                images.append(image)
            vectors.extend(cache.encode(encoder, images))
    finally:
        cache.close()
    np.savez_compressed(args.output / "vectors.npz", vectors=np.asarray(vectors))
    write_json(
        args.output / "manifest.json",
        {
            "contract": contract,
            "rows": crops["rows"],
            **({"frames": crops["frames"]} if "frames" in crops else {}),
            "vectors_sha256": digest(args.output / "vectors.npz"),
            "seconds": time.perf_counter() - started,
            "new_encoded_images": encoder.images,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "encode"):
        sub = commands.add_parser(command)
        sub.add_argument("--source", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        sub.add_argument("--device", default="cpu" if command == "prepare" else "mps")
        if command == "prepare":
            sub.add_argument("--video", type=Path, required=True)
            sub.add_argument("--sam", type=Path, required=True)
            sub.add_argument("--stride", type=int, default=5)
        else:
            sub.add_argument("--weights", type=Path, required=True)
            sub.add_argument("--adapted-weights", type=Path)
            sub.add_argument("--variant", choices=("masked", "aligned"), required=True)
            sub.add_argument(
                "--source-manifest",
                type=Path,
                help="Original feature manifest, required for provenance of older crop archives",
            )
    args = parser.parse_args()
    (prepare if args.command == "prepare" else encode)(args)


if __name__ == "__main__":
    main()
