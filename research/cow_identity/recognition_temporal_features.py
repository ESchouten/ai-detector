"""Frozen early-only descriptors for a bounded temporal metric-learning pilot."""

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from cutie_features import object_crops
from recognition_temporal_review import CLIP, ROOT, RUN, SELECTION, quality_rows
from recognition_temporal_review import OUTPUT as REVIEW
from smoke_runtime import CountedEncoder
from video_assessment import pixels_hash

from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.miewid import WEIGHTS_SHA256, MiewidEncoder

GALLERY = Path(".cache/cow-masked-reviewed-gallery-v1/manifest.json")
WEIGHTS = (
    Path.home()
    / ".cache/huggingface/hub/models--conservationxlabs--miewid-msv3/blobs"
    / WEIGHTS_SHA256
)


def positive_groups(rows):
    """Negatives only coexist; positives never cross interrupted quality runs."""
    eligible = [r for r in rows if r["second"] <= 419 and r["track_id"] < 4]
    runs, frames = {}, {}
    for row in eligible:
        runs.setdefault((row["track_id"], row["run_start"]), []).append(row)
        frames.setdefault(row["second"], []).append(row)
    groups = []
    for second, anchors in sorted(frames.items()):
        pairs = []
        for anchor in anchors:
            options = [
                r
                for r in runs[(anchor["track_id"], anchor["run_start"])]
                if 10 <= abs(r["second"] - second) <= 30
            ]
            if options:
                positive = min(
                    options,
                    key=lambda r: (abs(abs(r["second"] - second) - 20), r["second"]),
                )
                pairs.append(
                    {
                        "track_id": anchor["track_id"],
                        "anchor_second": second,
                        "positive_second": positive["second"],
                        "run_start": anchor["run_start"],
                    }
                )
        if len(pairs) >= 2:
            groups.append({"second": second, "pairs": pairs})
    return groups


def fingerprint_contract():
    return {
        "weights": WEIGHTS_SHA256,
        "preprocessing": "rgb-bilinear-stretch440-imagenet-gem-bn-l2-v1",
        "device": "mps",
        "precision": "float32",
        "libraries": {
            name: version(name) for name in ("torch", "torchvision", "timm", "Pillow")
        },
    }


def freeze(path):
    teacher = json.loads((RUN / "streaming.json").read_text())
    frames = [f for f in teacher["timeline"] if 0 <= f["second"] <= 629]
    if [f["second"] for f in frames] != list(range(630)):
        raise ValueError("All630 integer source frames required")
    quality = quality_rows(frames)
    groups = positive_groups(quality)
    gallery = [r for r in json.loads(GALLERY.read_text())["rows"] if r["second"] <= 419]
    files = [
        Path(__file__),
        ROOT / "test_recognition_temporal_features.py",
        ROOT / "recognition_temporal_review.py",
        ROOT / "recognition_masked_pilot.py",
        ROOT / "cutie_features.py",
        ROOT / "detection_cutie.py",
        ROOT / "detection_cutie_variants.py",
        ROOT / "video_assessment.py",
        ROOT / "benchmark.py",
        ROOT / "smoke_runtime.py",
        ROOT / "recognition_public_head.py",
        ROOT / "scoring.py",
        ROOT / "recognition_temporal.py",
        ROOT / "tracked_experiment.py",
        RUN / "streaming.json",
        CLIP / "sampled.json",
        CLIP / "sampled.avi",
        SELECTION,
        REVIEW / "manifest.json",
        REVIEW / "contact-sheet.jpg",
        GALLERY,
        WEIGHTS,
    ]
    files += [
        Path("detector/src/aidetector") / name
        for name in (
            "adapters/inference/miewid.py",
            "adapters/inference/identity.py",
            "adapters/inference/device.py",
            "domain/models.py",
        )
    ]
    files += [Path(row["foreground"]["path"]) for row in gallery]
    contract = fingerprint_contract()
    write_json(
        path,
        {
            "status": "FROZEN_EARLY_DESCRIPTOR_AND_ONE_CHECKPOINT_PILOT",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {str(p): digest(p) for p in files},
            "inputs": {
                "run": str(RUN),
                "clip": str(CLIP),
                "weights": str(WEIGHTS),
                "gallery": str(GALLERY),
            },
            "encoder_contract": contract,
            "encoder_fingerprint": hashlib.sha256(
                json.dumps(contract, sort_keys=True).encode()
            ).hexdigest(),
            "source_seconds": [0, 629],
            "cadence_seconds": 1,
            "batch_size": 8,
            "expected_source_crops": sum(len(f["boxes"]) for f in frames),
            "gallery_rows": gallery,
            "gallery_policy": "Exactly27 independently AI-reviewed refs at<=419s; all6known identities. No reference replacement or later photos. Photos from existing reviewed actual-proposal teacher, re-encoded identically here. No7/8 reference.",
            "review": {
                "reviewer": "root",
                "method": "Prediction-only fixed16crop/contextsheet before encoding",
                "conclusion": "All16 coherent substantial singlecowforeground; no obvious merge/background-only crop. Clipped extremities and narrow/curling poses retained. Not biological certification of whole pool; no filtering changed.",
                "sheet_sha256": digest(REVIEW / "contact-sheet.jpg"),
            },
            "training_quality_rows": [
                r for r in quality if r["second"] <= 419 and r["track_id"] < 4
            ],
            "training_groups": groups,
            "training_counts": {
                "groups": len(groups),
                "anchor_pairs": sum(len(g["pairs"]) for g in groups),
                "by_slot": dict(
                    Counter(p["track_id"] for g in groups for p in g["pairs"])
                ),
            },
            "pilot": {
                "training_window": [0, 419],
                "training_slots": [0, 1, 2, 3],
                "embargo": [420, 449],
                "calibration_window": [450, 629],
                "untrained_known_cows": [5, 6],
                "withheld_unknown_cows": [7, 8],
                "data_flow": "Only training_groups enter optimization. Encoded other rows are isolated evaluation cache; no feature normalization fitting/PCA/BN adaptation. Unknown7/8 never supply positives, negatives, classifier weights or gradients.",
                "positives": "Same stable slot within uninterrupted fixed-quality run; gap10..30s, closest absolute gap20s, tie earlier. No pair across run boundary.",
                "negatives": "Other qualified anchor slots in exactly same source frame, only1..4. No cross-frame/cross-batch negatives and no unknown negatives.",
                "architecture": "Same-dimensional residual: normalize(x +0.1*Wout*Dropout.1(GELU(LayerNorm(Win*x))));2152→256→2152; both Linear biasfalse; Win standard PyTorch Kaiming-uniform initialization, Wout exactlyzero; initialoutputequals normalizedbase; backbone frozen",
                "epochs": 20,
                "seed": 42,
                "batch_frames": 16,
                "optimizer": "AdamW lr.001 weight_decay.0001; no scheduler",
                "loss": "Per-anchor crossentropy of its temporal-positive cosine against only same-frame other-anchor cosines, all dividedby.1; average over eligible anchors; add1.0*mean(1-cosine(base,adapted)) over only those training anchors/positives",
                "augmentation": "Only existing head dropout.1; no feature/noise or image augmentation",
                "checkpoint_epochs": [20],
                "descriptor": "Residual2152Doutput retains original cosinegeometry at initialization; no blend/threshold search",
                "selection": "Only baseline versus fixed epoch20. Fixed similarity.65/margin.10/3same-candidate observations/maxgap5s. Retain duplicates/geometry abstention and full one-to-one visible-animal denominators. Baseline eligible; candidate must meet99%precision/<=1%unknown false naming and improve correct coverage on450..629. No threshold grid, checkpoint search, retraining on5/6 or late-query-based selection. Report untrained5/6 separately.",
                "reset": "Fresh identity state at450; known seed labels/quarantine/named_track_ids NEVER initialize matcher labels. Stable slot used only for causal3observation state, never candidate name. Later930+ queries require separate frozen evaluation after calibration decision.",
                "limits": "Teacher already assessed on this farm; four training identities and onecamera are a weak adaptation pilot, not fresh generalization. Calibration includes teacher-history geometry; no biological identity field enters inference. Dense crops represent inferred continuity, not thousands of farmer confirmations.",
            },
            "crop": "Exact object_crops: largest8connected foreground, tight original-convention bounds, background127, no alignment; all5011 actual slots retained for cache including rejected/unknown/embargo observations",
            "evaluation_labels": "Not opened during encoding/training. Calibration later uses unchanged publisher all8 truth+unmatched named errors; no truth-dependent row deletion/repair.",
            "libraries": {
                name: version(name)
                for name in (
                    "torch",
                    "torchvision",
                    "timm",
                    "Pillow",
                    "numpy",
                    "opencv-python",
                    "safetensors",
                )
            },
            "resource_limits": {
                "max_mps_driver_bytes": 8 * 1024**3,
                "max_batch": 8,
                "torch_cpu_threads": 2,
            },
        },
    )


def checked(path):
    protocol = json.loads(path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    if fingerprint_contract() != protocol["encoder_contract"]:
        raise ValueError("Encoder environment changed")
    return protocol


def source_frames(protocol):
    clip = Path(protocol["inputs"]["clip"])
    metadata = json.loads((clip / "sampled.json").read_text())
    capture = cv2.VideoCapture(str(clip / "sampled.avi"))
    try:
        for source in metadata["rows"]:
            second = source["second"]
            if second > 629:
                break
            if not capture.grab():
                raise ValueError("Clip ended early")
            if second != int(second):
                continue
            ok, image = capture.retrieve()
            if not ok or pixels_hash(image) != source["pixels_sha256"]:
                raise ValueError("Exact source pixels changed")
            yield int(second), image
    finally:
        capture.release()


def frame_crops(frame, image, run):
    if pixels_hash(image) != frame["source_pixels_sha256"]:
        raise ValueError("Teacher source differs")
    path = run / "masks" / f"{int(frame['second'])}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Original teacher mask changed")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if (
        mask is None
        or mask.shape != image.shape[:2]
        or mask.dtype not in (np.uint8, np.uint16)
        or not set(np.unique(mask))
        <= {0, *(item["track_id"] + 1 for item in frame["objects"])}
    ):
        raise ValueError("Invalid indexed teacher mask")
    boxes, crops, _ = object_crops(image, mask)
    if [b["track_id"] for b in boxes] != [b["track_id"] for b in frame["boxes"]]:
        raise ValueError("Do not lose original slot inventory")
    return boxes, crops


def encode_crops(cache, encoder, crops, limit):
    import torch

    vectors, peak = [], 0
    for offset in range(0, len(crops), 8):
        vectors.extend(cache.encode(encoder, crops[offset : offset + 8]))
        peak = max(peak, torch.mps.driver_allocated_memory())
        if peak > limit:
            raise MemoryError("MPS driver budget exceeded; preserve partial cache")
    return vectors, peak


def collect(protocol_path, output):
    import torch

    protocol = checked(protocol_path)
    if (output / "manifest.json").exists():
        raise FileExistsError("Preserve complete feature result")
    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Frozen descriptor pass requires actual MPS")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    encoder = CountedEncoder(
        MiewidEncoder(output / "models", "mps", Path(protocol["inputs"]["weights"]))
    )
    if encoder.fingerprint != protocol["encoder_fingerprint"]:
        raise ValueError("Actual encoder differs from frozen contract")
    run = Path(protocol["inputs"]["run"])
    teacher = json.loads((run / "streaming.json").read_text())
    timeline = {int(f["second"]): f for f in teacher["timeline"] if f["second"] <= 629}
    rows, vectors, frames = [], [], []
    cache = EmbeddingCache(output / "embeddings.sqlite")
    peak = 0
    try:
        for second, image in source_frames(protocol):
            frame = timeline[second]
            boxes, crops = frame_crops(frame, image, run)
            encoded, allocation = encode_crops(
                cache,
                encoder,
                crops,
                protocol["resource_limits"]["max_mps_driver_bytes"],
            )
            vectors.extend(encoded)
            peak = max(peak, allocation)
            frame_rows = []
            for box, crop in zip(boxes, crops, strict=True):
                frame_rows.append(len(rows))
                rows.append(
                    {
                        "kind": "observation",
                        "second": second,
                        "track_id": box["track_id"],
                        "box": [box[k] for k in ("x1", "y1", "x2", "y2")],
                        "mask_sha256": frame["mask_sha256"],
                        "pixels_sha256": pixels_hash(crop),
                    }
                )
            frames.append({"second": second, "rows": frame_rows})
            if second % 100 == 0:
                print(
                    json.dumps(
                        {
                            "second": second,
                            "rows": len(rows),
                            "elapsed": time.perf_counter() - started,
                            "mps_driver_peak": peak,
                        }
                    ),
                    flush=True,
                )
        for ref in protocol["gallery_rows"]:
            crop = cv2.imread(ref["foreground"]["path"])
            if pixels_hash(crop) != ref["foreground"]["pixels_sha256"]:
                raise ValueError("Reviewed reference pixels changed")
            encoded, allocation = encode_crops(
                cache,
                encoder,
                [crop],
                protocol["resource_limits"]["max_mps_driver_bytes"],
            )
            vectors.extend(encoded)
            peak = max(peak, allocation)
            rows.append(
                {
                    "kind": "gallery",
                    "cow": ref["cow"],
                    "second": ref["second"],
                    "track_id": ref["track_id"],
                    "pixels_sha256": pixels_hash(crop),
                    "source": ref["foreground"],
                }
            )
    finally:
        cache.close()
    values = np.asarray(vectors, dtype=np.float32)
    if (
        len(rows) != protocol["expected_source_crops"] + len(protocol["gallery_rows"])
        or len(frames) != 630
        or values.shape != (len(rows), 2152)
        or not np.isfinite(values).all()
    ):
        raise ValueError("Incomplete or nonfinite descriptor pass")
    np.savez_compressed(output / "vectors.npz", vectors=values)
    write_json(
        output / "manifest.json",
        {
            "contract": {
                "protocol_sha256": digest(protocol_path),
                "encoder_fingerprint": encoder.fingerprint,
                "teacher_sha256": digest(run / "streaming.json"),
                "crop": protocol["crop"],
            },
            "rows": rows,
            "frames": frames,
            "vectors_sha256": digest(output / "vectors.npz"),
            "elapsed_seconds": time.perf_counter() - started,
            "new_encoded_images": encoder.images,
            "new_encoder_batches": encoder.calls,
            "mps_driver_peak": peak,
        },
    )
    print(
        json.dumps(
            {
                "complete": True,
                "rows": len(rows),
                "seconds": time.perf_counter() - started,
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "encode", "check"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            raise FileExistsError("Preserve previous freeze")
        freeze(args.protocol)
    elif args.mode == "check":
        p = checked(args.protocol)
        print(
            json.dumps(
                {
                    "valid": True,
                    "files": len(p["files"]),
                    "fingerprint": p["encoder_fingerprint"],
                    "training_counts": p["training_counts"],
                }
            )
        )
    else:
        collect(args.protocol, args.output)


if __name__ == "__main__":
    main()
