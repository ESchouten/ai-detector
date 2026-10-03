"""CPU-only coat-pattern matching experiment on the frozen development panels.

Uses OpenCV SIFT, mutual ratio matches and affine RANSAC. This is a complementary
research baseline, not a replacement for the application identity encoder.
Publisher crops are oracle inputs; full-pipeline performance is not measured.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

CONTRACT = {
    "version": 1,
    "opencv": cv2.__version__,
    "extractor": "SIFT / RootSIFT",
    "max_features": 256,
    "max_dimension": 320,
    "mask": "ellipse centered in crop; axes 45% of width/height",
    "ratio": 0.8,
    "matching": "mutual nearest + ratio in both directions",
    "geometry": "partial affine RANSAC; 3px error, 2000 iterations, seed0",
    "score": "inlier count, zero when fewer than4 or hull area below0.5%",
}


def extract(image):
    height, width = image.shape[:2]
    scale = CONTRACT["max_dimension"] / max(height, width)
    gray = cv2.cvtColor(cv2.resize(image, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    mask = np.zeros_like(gray)
    cv2.ellipse(
        mask, (w // 2, h // 2), (int(w * 0.45), int(h * 0.45)), 0, 0, 360, 255, -1
    )
    keypoints, descriptors = cv2.SIFT_create(nfeatures=256).detectAndCompute(gray, mask)
    points = np.asarray([point.pt for point in keypoints], dtype=np.float32).reshape(
        -1, 2
    )
    if descriptors is None:
        descriptors = np.empty((0, 128), dtype=np.float32)
    else:
        descriptors = np.sqrt(
            descriptors / np.maximum(descriptors.sum(axis=1, keepdims=True), 1e-12)
        )
    return points, descriptors, np.asarray((h, w), dtype=np.int32)


def geometric_score(query, reference):
    points, descriptors, size = query
    other_points, other_descriptors, other_size = reference
    if min(len(points), len(other_points)) < 4:
        return 0
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward = matcher.knnMatch(descriptors, other_descriptors, k=2)
    reverse = matcher.knnMatch(other_descriptors, descriptors, k=2)
    backward = {
        first.queryIdx: first.trainIdx
        for first, second in reverse
        if first.distance < CONTRACT["ratio"] * second.distance
    }
    pairs = [
        (first.queryIdx, first.trainIdx)
        for first, second in forward
        if first.distance < CONTRACT["ratio"] * second.distance
        and backward.get(first.trainIdx) == first.queryIdx
    ]
    if len(pairs) < 4:
        return 0
    indices = np.asarray(pairs)
    source, target = points[indices[:, 0]], other_points[indices[:, 1]]
    cv2.setRNGSeed(0)
    _, inliers = cv2.estimateAffinePartial2D(
        source, target, method=cv2.RANSAC, ransacReprojThreshold=3, maxIters=2000
    )
    if inliers is None or inliers.sum() < 4:
        return 0
    chosen = inliers.ravel().astype(bool)
    spread = min(
        cv2.contourArea(cv2.convexHull(source[chosen])) / np.prod(size),
        cv2.contourArea(cv2.convexHull(target[chosen])) / np.prod(other_size),
    )
    return int(chosen.sum()) if spread >= 0.005 else 0


def features(rows, indices, video, cache):
    cache.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    current_frame = None
    image = None
    contract_hash = hashlib.sha256(
        json.dumps(CONTRACT, sort_keys=True).encode()
    ).hexdigest()
    result = {}
    try:
        for index in indices:
            row = rows[index]
            path = cache / f"{contract_hash}-{row['pixels_sha256']}.npz"
            if path.exists():
                with np.load(path, allow_pickle=False) as arrays:
                    result[index] = tuple(
                        arrays[name] for name in ("points", "descriptors", "size")
                    )
                continue
            if current_frame != row["frame"]:
                capture.set(cv2.CAP_PROP_POS_FRAMES, row["frame"] - 1)
                ok, image = capture.read()
                if not ok:
                    raise ValueError(f"Cannot decode frame {row['frame']}")
                current_frame = row["frame"]
            x1, y1, x2, y2 = row["box"]
            crop = image[y1:y2, x1:x2].copy()
            if pixels_hash(crop) != row["pixels_sha256"]:
                raise ValueError("Crop pixels differ from the recognition manifest")
            points, descriptors, size = extract(crop)
            np.savez_compressed(path, points=points, descriptors=descriptors, size=size)
            result[index] = points, descriptors, size
    finally:
        capture.release()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--gallery",
        type=Path,
        help="JSON list of enrollment row indexes; otherwise uniform10",
    )
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--cache", type=Path, default=Path(".cache/cow-local-features"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    manifest = json.loads(args.manifest.read_text())
    rows = manifest["rows"]
    if digest(args.video) != manifest["contract"]["video_sha256"]:
        raise ValueError("Video differs from the recognition manifest")
    if args.gallery:
        gallery = json.loads(args.gallery.read_text())
    else:
        gallery = []
        for cow in range(1, 7):
            candidates = [
                i
                for i, row in enumerate(rows)
                if row["panel"] == "enrollment" and row["cow"] == cow
            ]
            gallery.extend(
                candidates[i]
                for i in np.linspace(0, len(candidates) - 1, 10, dtype=int)
            )
    if any(
        rows[i]["panel"] != "enrollment" or rows[i]["cow"] not in range(1, 7)
        for i in gallery
    ):
        raise ValueError("References must be known-cow enrollment photos")
    queries = [
        i
        for i, row in enumerate(rows)
        if row["panel"] != "enrollment" and row["second"] % args.stride == 0
    ]
    if any(
        rows[i]["panel"] not in ("development", "development_later", "calibration")
        for i in queries
    ):
        raise ValueError("Only development/calibration panels allowed")
    started = time.perf_counter()
    extracted = features(rows, sorted(set(gallery + queries)), args.video, args.cache)
    feature_seconds = time.perf_counter() - started
    scores = np.zeros((len(queries), len(gallery)), dtype=np.float32)
    for q, index in enumerate(queries):
        for g, reference in enumerate(gallery):
            scores[q, g] = geometric_score(extracted[index], extracted[reference])
        if (q + 1) % 100 == 0:
            print(json.dumps({"scored": q + 1, "queries": len(queries)}), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output / "scores.npz", scores=scores, queries=queries, gallery=gallery
    )
    write_json(
        args.output / "manifest.json",
        {
            "contract": CONTRACT,
            "input_manifest_sha256": digest(args.manifest),
            "scores_sha256": digest(args.output / "scores.npz"),
            "gallery": gallery,
            "queries": queries,
            "feature_seconds": feature_seconds,
            "total_seconds": time.perf_counter() - started,
            "scope": "Oracle-crop local descriptor diagnostic; no final-test frames",
        },
    )


if __name__ == "__main__":
    main()
