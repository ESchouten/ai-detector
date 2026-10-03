"""Bounded ALIKED/LightGlue control on cached foreground crops.

Uses the upstream LightGlue package in the separate research environment. The
application receives no new dependency. Cached global features choose reference
candidates without query labels; all expensive local features are cached too.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from benchmark import digest, write_json
from lightglue import ALIKED, LightGlue
from recognition_experiment import select_gallery


def cached_features(extractor, path, cache, fingerprint):
    key = hashlib.sha256(f"{fingerprint}:{digest(path)}".encode()).hexdigest()
    destination = cache / f"{key}.npz"
    if destination.exists():
        with np.load(destination, allow_pickle=False) as values:
            return {name: torch.from_numpy(values[name]) for name in values.files}
    image = cv2.imread(str(path))
    tensor = (
        torch.from_numpy(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        .permute(2, 0, 1)
        .float()
        / 255
    )
    with torch.inference_mode():
        values = extractor.extract(tensor, resize=512)
    np.savez_compressed(
        destination, **{name: value.cpu().numpy() for name, value in values.items()}
    )
    return values


def geometric_matches(first, second, matches):
    pairs = matches["matches"][0].cpu().numpy()
    if len(pairs) < 4:
        return 0
    source = first["keypoints"][0].cpu().numpy()[pairs[:, 0]]
    target = second["keypoints"][0].cpu().numpy()[pairs[:, 1]]
    size = second["image_size"][0].cpu().numpy()
    cv2.setRNGSeed(0)
    _, inliers = cv2.estimateAffine2D(
        source,
        target,
        method=cv2.RANSAC,
        ransacReprojThreshold=float(size.max()) * 0.015,
        maxIters=2000,
    )
    if inliers is None or inliers.sum() < 4:
        return 0
    points = target[inliers.ravel().astype(bool)]
    spread = cv2.contourArea(cv2.convexHull(points)) / np.prod(size)
    return int(inliers.sum()) if spread >= 0.005 else 0


def run(args):
    torch.set_num_threads(2)
    manifest = json.loads((args.features / "manifest.json").read_text())
    crops = json.loads((args.crops / "crops.json").read_text())
    if crops["contract"]["source_manifest_sha256"] != digest(
        args.features / "manifest.json"
    ):
        raise ValueError("Crop and global feature manifests differ")
    rows = manifest["rows"]
    with np.load(args.features / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    gallery = select_gallery(rows, vectors, "diverse10")
    queries = np.asarray(
        [
            i
            for i, row in enumerate(rows)
            if row["panel"] != "enrollment" and row["second"] in args.seconds
        ]
    )
    lookup = {(row["panel"], row["second"], row["cow"]): row for row in crops["rows"]}
    extractor = ALIKED(max_num_keypoints=256).eval()
    matcher = LightGlue(features="aliked", flash=False).eval()
    checkpoints = Path(torch.hub.get_dir()) / "checkpoints"
    contract = {
        "upstream": "https://github.com/cvg/LightGlue",
        "commit": "eb42fee2d71449efb0aa5c10549752b5d75384d8",
        "weights": {
            name: digest(checkpoints / name)
            for name in ("aliked-n16.pth", "aliked_lightglue_v0-1_arxiv.pth")
        },
        "extractor": "ALIKED n16, 256 maximum keypoints, longest side512",
        "matcher": "LightGlue official aliked, flash=False, default pruning",
        "crop_contract": crops["contract"],
        "score": "affine RANSAC inliers, error1.5%reference longest side, >=4inliers and0.5%reference area; raw count also retained",
        "candidates_per_cow": args.candidates,
        "device": "cpu",
        "torch": torch.__version__,
        "opencv": cv2.__version__,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                key: contract[key]
                for key in ("weights", "extractor", "crop_contract", "torch", "opencv")
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    features = {}
    for i in sorted(set(gallery) | set(queries)):
        row = rows[i]
        crop = lookup[row["panel"], row["second"], row["cow"]]
        features[i] = cached_features(
            extractor,
            args.crops / crop["variants"]["masked"]["path"],
            args.cache,
            fingerprint,
        )
    extraction_seconds = time.perf_counter() - started
    scores = np.zeros((len(queries), len(gallery)), dtype=np.float32)
    raw_scores = np.zeros_like(scores)
    owners = np.asarray([rows[i]["cow"] for i in gallery])
    global_scores = vectors[queries] @ vectors[gallery].T
    pairs = 0
    with torch.inference_mode():
        for index, query in enumerate(queries):
            candidates = np.concatenate(
                [
                    np.flatnonzero(owners == cow)[
                        np.argsort(-global_scores[index, owners == cow])[
                            : args.candidates
                        ]
                    ]
                    for cow in range(1, 7)
                ]
            )
            for column in candidates:
                result = matcher(
                    {"image0": features[query], "image1": features[gallery[column]]}
                )
                raw_scores[index, column] = len(result["matches"][0])
                scores[index, column] = geometric_matches(
                    features[query], features[gallery[column]], result
                )
                pairs += 1
            if index % 10 == 0:
                print(json.dumps({"queries": index + 1, "pairs": pairs}), flush=True)
    np.savez_compressed(
        args.output / "scores.npz",
        queries=queries,
        gallery=gallery,
        scores=scores,
        raw_scores=raw_scores,
    )
    write_json(
        args.output / "manifest.json",
        {
            "contract": contract,
            "input_manifest_sha256": digest(args.features / "manifest.json"),
            "scores_sha256": digest(args.output / "scores.npz"),
            "seconds": args.seconds,
            "total_seconds": time.perf_counter() - started,
            "extraction_seconds": extraction_seconds,
            "pairs": pairs,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, nargs="+", default=[330, 930, 1230])
    parser.add_argument("--candidates", type=int, default=10)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
