"""Frozen all-six farm adaptation data and lossless spatial-prefix cache."""

import argparse
import json
import random
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from PIL import Image
from recognition_spatial_tail_model import normalized_tail, split_model
from recognition_temporal_features import checked as checked_descriptors
from recognition_temporal_features import frame_crops, source_frames
from recognition_temporal_head import read_features
from recognition_temporal_review import quality_rows
from video_assessment import pixels_hash

from aidetector.adapters.inference.miewid import MiewidEncoder

ROOT = Path(__file__).parent
DESCRIPTOR_PROTOCOL = ROOT / "recognition_temporal_pilot_v2_protocol.json"
HEAD_PROTOCOL = ROOT / "recognition_temporal_head_protocol.json"
FEATURES = Path(".cache/cow-temporal-dense-v2")
BASELINE = Path(".cache/cow-temporal-head-v1/calibration.json")
REVIEW = Path(".cache/cow-spatial-tail-review")


def all_six_groups(rows):
    rows = [r for r in rows if r["second"] <= 419 and r["track_id"] < 6]
    runs, frames = {}, {}
    for row in rows:
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
                partner = min(
                    options,
                    key=lambda r: (abs(abs(r["second"] - second) - 20), r["second"]),
                )
                pairs.append(
                    {
                        "track_id": anchor["track_id"],
                        "anchor_second": second,
                        "positive_second": partner["second"],
                        "run_start": anchor["run_start"],
                    }
                )
        if len(pairs) >= 2:
            groups.append({"second": second, "pairs": pairs})
    return groups


def training_schedule(groups, manifest):
    positions = {
        (r["second"], r["track_id"]): i
        for i, r in enumerate(manifest["rows"])
        if r["kind"] == "observation"
    }
    rng = random.Random(42)
    schedule, order = [], []
    for step in range(1, 201):
        if not order:
            order = rng.sample(range(len(groups)), len(groups))
        group = groups[order.pop()]
        pairs = sorted(
            rng.sample(group["pairs"], min(4, len(group["pairs"]))),
            key=lambda pair: pair["track_id"],
        )
        indices = [positions[(p["anchor_second"], p["track_id"])] for p in pairs] + [
            positions[(p["positive_second"], p["track_id"])] for p in pairs
        ]
        schedule.append(
            {
                "step": step,
                "second": group["second"],
                "pairs": pairs,
                "source_indices": indices,
            }
        )
    return schedule


def freeze(path):
    descriptor = checked_descriptors(DESCRIPTOR_PROTOCOL)
    manifest, _ = read_features(FEATURES, DESCRIPTOR_PROTOCOL)
    earlier = json.loads(HEAD_PROTOCOL.read_text())
    teacher = json.loads(
        (Path(descriptor["inputs"]["run"]) / "streaming.json").read_text()
    )
    quality = quality_rows(teacher["timeline"])
    groups = all_six_groups(quality)
    schedule = training_schedule(groups, manifest)
    used = {i for step in schedule for i in step["source_indices"]}
    bank = earlier["dense_bank"]["indices"]
    calibration = {
        i
        for frame in manifest["frames"]
        if 450 <= frame["second"] <= 629
        for i in frame["rows"]
    }
    selected = sorted(used | set(bank) | calibration)
    sources = [
        Path(__file__),
        ROOT / "recognition_spatial_tail_model.py",
        ROOT / "recognition_spatial_tail_train.py",
        ROOT / "test_recognition_spatial_tail_model.py",
        ROOT / "test_recognition_spatial_tail_data.py",
        ROOT / "test_recognition_spatial_tail_train.py",
        DESCRIPTOR_PROTOCOL,
        HEAD_PROTOCOL,
        FEATURES / "manifest.json",
        FEATURES / "vectors.npz",
        ROOT / "recognition_temporal_head.py",
        ROOT / "recognition_masked_replay.py",
        ROOT / "recognition_temporal_review.py",
        ROOT / "recognition_spatial_tail_review.py",
        ROOT / "results/2026-10-03/recognition/spatial-tail-review-selection.json",
        REVIEW / "manifest.json",
        REVIEW / "contact-sheet.jpg",
        BASELINE,
    ]
    review = json.loads((REVIEW / "manifest.json").read_text())
    sources += [Path(row[key]) for row in review["rows"] for key in ("crop", "context")]
    write_json(
        path,
        {
            "status": "FROZEN_SPATIAL_TAIL_FARM_PILOT_BEFORE_PREFIX_OR_TRAINING",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {str(p): digest(p) for p in sources},
            "descriptor_protocol": str(DESCRIPTOR_PROTOCOL),
            "features": str(FEATURES),
            "baseline_report": str(BASELINE),
            "review": {
                "method": "Same four fixed105-second bins/longest-quality-run midpoint, no backfill, newly trained slots5/6 only. Seven crops because slot5 has no eligible final-bin run.",
                "root_visual_verdict": "All seven show one principal cattle body. Slot5 remains near the same wall; slot6 at172s has crowded overlap but mask appears one body. No obvious two-cow mask merger. Preserve every selected crop; limited AI review does not certify biological lineage or all pseudo-labels.",
                "sheet_sha256": review["sheet_sha256"],
            },
            "source_indices": selected,
            "bank_source_indices": bank,
            "training_steps": schedule,
            "counts": {
                "eligible_groups": len(groups),
                "training_unique_crops": len(used),
                "calibration_crops": len(calibration),
                "bank_references": len(bank),
                "prefix_crops": len(selected),
                "training_anchor_pairs_per_slot": dict(
                    Counter(p["track_id"] for step in schedule for p in step["pairs"])
                ),
            },
            "training": {
                "scope": "All6initial-confirmed noisyteacherlineages0–419; not unseen-identitytransfer. No7/8 gradients/negatives; fixed450–629 exposedcalibration and30secondembargo. No3000+pixels or laterqueries.",
                "pairs": "Exactly preceding frozen same-frame negatives/within-unbroken-quality-run10–30s positive rule extendedfrom4to6knownslots; nearest20s gap, earlier tie. Randomseed42 picks one contemporaneous group/step, without replacement until pool exhausted, max4anchors+4partners. Entire200step schedule stored before prefix inference.",
                "architecture": "Exact reviewedMIEWid last2 InvertedResidual blocks backbone.blocks.5.22/23 and following conv_head only; identicalGeM/embeddingBN/L2output; frozenprefix stops before block5.22.",
                "frozen": "Allotherparameters, allBatchNormstats+affine, GeM parameter/classifier; entiremodel/tail evalmode for deterministicnormalization/stochasticdepth, autograd enabled onlydeclaredtailparams.",
                "steps": 200,
                "checkpoint_steps": [200],
                "seed": 42,
                "batch_max_crops": 8,
                "optimizer": "AdamW lr1e-5 weight_decay1e-4; gradientL2normclip5,error_if_nonfiniteTrue; no scheduler",
                "loss": "Sameframe-only contrastive crossentropyT.1 +1.0*mean(1-cosine(originalMIEWdescriptor,adapteddescriptor)) on onlytraininganchors/partners; no crossbatchnegatives or newaugmentation",
                "baseline": "Untouched originalencoder and exact alreadyfrozen96lineagereferences; adaptedmodel uses same96observations, no bankreselec­tion or27referencebranch",
                "decision": "Existing predict_panel: fixed.65similarity/.10distinctmargin/3observations/maxgap5; no overlapveto for isolatedmasks, minside64/borderreject, freshnamingat450. No transferredseednames or groundtruth in predictions.",
                "selection": "One200stepcandidate only versus untouchedbankbaseline; preserve all visibleknown/unknown/unmatched categories. Report99%precision/60%coverage/<=1%unknownfullgoal separately; no threshold/epoch/grid or laterqueryselection.",
            },
            "cache": {
                "dtype": "float32",
                "expected_shape_per_crop": [328, 14, 14],
                "input": "Exact existing maskedBGRpixels→officialRGBbilinear440/ImageNet normalization",
                "binding": "officialweights+cutpoint+code+libraries+sourcecrop hashes; no reusablewrongencoderlabels",
                "full_tail_parity": {
                    "scope": "First actual batch full-network versus split-prefix/tail output; every cached crop additionally compared to its immutable original full-network descriptor below.",
                    "maximum_absolute_error": 1e-5,
                    "minimum_cosine": 0.999999,
                },
                "cached_original_vector_parity": {
                    "maximum_absolute_error": 1e-5,
                    "minimum_cosine": 0.999999,
                },
                "before_training": "Save completeprefixcache+allparitymetrics+binarySHA before freezing exacttrainingcachebinding; failclosedonanyparityerror",
            },
            "resources": {
                "device": "mps",
                "precision": "float32",
                "cpu_threads": 2,
                "batch_max": 8,
                "driver_bytes_cap": 8 * 1024**3,
            },
            "limits": "Earlylocalizer/teacher fromsamevideo, AI-reviewed initial identities andmaskquality, not independentlyhumanverified allpseudo-labels. Exposedcalibration, no field/newfarm/physicalreentry or applicationpromotion claim.",
        },
    )


def checked(path):
    protocol = json.loads(path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen spatial input changed: {name}")
    descriptor = checked_descriptors(Path(protocol["descriptor_protocol"]))
    manifest, vectors = read_features(
        Path(protocol["features"]), Path(protocol["descriptor_protocol"])
    )
    return protocol, descriptor, manifest, vectors


def parity(a, b):
    return {
        "max_absolute_error": float(np.abs(a - b).max()),
        "minimum_cosine": float(np.sum(a * b, axis=1).min()),
    }


def checked_parity(stats):
    if stats["max_absolute_error"] > 1e-5 or stats["minimum_cosine"] < 0.999999:
        raise ValueError(f"Prefix/full/cache representation mismatch: {stats}")


def encode_batch(encoder, prefix, tail, crops, expected, check_full):
    pixels = torch.stack(
        [encoder.transform(Image.fromarray(crop[:, :, ::-1])) for crop in crops]
    ).to("mps")
    with torch.inference_mode():
        maps = prefix(pixels)
        split = normalized_tail(tail, maps)
        full = (
            torch.nn.functional.normalize(encoder.model(pixels), dim=1)
            if check_full
            else None
        )
        arrays = maps.cpu().numpy().copy()
        split = split.cpu().numpy()
        full = full.cpu().numpy() if full is not None else None
    exact, historical = (
        parity(split, full) if full is not None else None,
        parity(split, expected),
    )
    if exact is not None:
        checked_parity(exact)
    checked_parity(historical)
    if (
        arrays.shape[1:] != (328, 14, 14)
        or arrays.dtype != np.float32
        or not np.isfinite(arrays).all()
    ):
        raise ValueError("Prefix map contract changed")
    return arrays, exact, historical


def verify_crop_pixels(batch, manifest):
    if any(
        pixels_hash(crop) != manifest["rows"][i]["pixels_sha256"] for i, crop in batch
    ):
        raise ValueError("Exact previouslycached maskedcrop pixels changed")


def cache_prefix(args):
    protocol, descriptor, manifest, vectors = checked(args.protocol)
    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual MPS required")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    encoder = MiewidEncoder(
        args.output / "models", "mps", Path(descriptor["inputs"]["weights"])
    )
    if encoder.fingerprint != descriptor["encoder_fingerprint"]:
        raise ValueError("Original encoder changed")
    prefix, tail = split_model(encoder.model)
    selected = protocol["source_indices"]
    selected_lookup = {index: i for i, index in enumerate(selected)}
    indexed = {
        (manifest["rows"][i]["second"], manifest["rows"][i]["track_id"]): i
        for i in selected
    }
    run = Path(descriptor["inputs"]["run"])
    teacher = json.loads((run / "streaming.json").read_text())
    timeline = {int(f["second"]): f for f in teacher["timeline"] if f["second"] <= 629}
    maps = np.lib.format.open_memmap(
        args.output / "maps.npy",
        mode="w+",
        dtype=np.float32,
        shape=(len(selected), 328, 14, 14),
    )
    seen, comparisons, peak = set(), [], 0
    for second, image in source_frames(descriptor):
        if not any(key[0] == second for key in indexed):
            continue
        boxes, crops = frame_crops(timeline[second], image, run)
        positions = [
            (indexed[(second, b["track_id"])], crop)
            for b, crop in zip(boxes, crops, strict=True)
            if (second, b["track_id"]) in indexed
        ]
        for offset in range(0, len(positions), 8):
            batch = positions[offset : offset + 8]
            indices, images = zip(*batch, strict=True)
            verify_crop_pixels(batch, manifest)
            arrays, exact, historical = encode_batch(
                encoder, prefix, tail, images, vectors[list(indices)], not comparisons
            )
            for source_index, value in zip(indices, arrays, strict=True):
                maps[selected_lookup[source_index]] = value
                seen.add(source_index)
            comparisons.append(
                {
                    "second": second,
                    "source_indices": list(indices),
                    "full_split": exact,
                    "original_cache": historical,
                }
            )
            peak = max(peak, torch.mps.driver_allocated_memory())
            if peak > protocol["resources"]["driver_bytes_cap"]:
                raise MemoryError(
                    "MPS cap exceeded; preserve partialcache withouttraining"
                )
        if second % 100 == 0:
            print(
                json.dumps(
                    {
                        "second": second,
                        "cached_crops": len(seen),
                        "elapsed": time.perf_counter() - started,
                        "driver_peak": peak,
                    }
                ),
                flush=True,
            )
    if seen != set(selected):
        raise ValueError("Missing prefix observation")
    maps.flush()
    del maps
    write_json(
        args.output / "manifest.json",
        {
            "status": "COMPLETE_PARITY_PASSED_BEFORE_TRAINING",
            "protocol_sha256": digest(args.protocol),
            "encoder_fingerprint": encoder.fingerprint,
            "rows": [{"source_index": i, **manifest["rows"][i]} for i in selected],
            "maps_sha256": digest(args.output / "maps.npy"),
            "parity": comparisons,
            "elapsed_seconds": time.perf_counter() - started,
            "driver_peak": peak,
        },
    )
    print(
        json.dumps(
            {
                "complete": True,
                "rows": len(selected),
                "seconds": time.perf_counter() - started,
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "check", "cache"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            raise FileExistsError("Preserve earlierfreeze")
        freeze(args.protocol)
    elif args.mode == "check":
        protocol, _, _, _ = checked(args.protocol)
        print(json.dumps({"valid": True, "counts": protocol["counts"]}))
    else:
        cache_prefix(args)


if __name__ == "__main__":
    main()
