"""Fixed RootSIFT passage control, with inspectable geometric evidence.

The extractor is the existing local_features implementation. The detailed
matcher mirrors its frozen scalar function so earlier experiment source hashes
remain intact; parity is tested before this distinct control is frozen.
"""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from local_features import CONTRACT, extract
from video_assessment import pixels_hash

from aidetector.domain.identity import choose_identity
from aidetector.domain.models import IdentityMatch

MIN_INLIERS = 11
MIN_MARGIN = 5


def evidence(query, reference):
    points, descriptors, size = query
    other_points, other_descriptors, other_size = reference
    result = {
        "score": 0,
        "mutual_pairs": 0,
        "inliers": 0,
        "query_hull_fraction": 0.0,
        "reference_hull_fraction": 0.0,
        "query_size": size.tolist(),
        "reference_size": other_size.tolist(),
        "query_points": [],
        "reference_points": [],
    }
    if min(len(points), len(other_points)) < 4:
        return result
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
    result["mutual_pairs"] = len(pairs)
    if len(pairs) < 4:
        return result
    indices = np.asarray(pairs)
    source, target = points[indices[:, 0]], other_points[indices[:, 1]]
    cv2.setRNGSeed(0)
    transform, inliers = cv2.estimateAffinePartial2D(
        source, target, method=cv2.RANSAC, ransacReprojThreshold=3, maxIters=2000
    )
    if inliers is None or inliers.sum() < 4:
        return result
    chosen = inliers.ravel().astype(bool)
    query_spread = float(
        cv2.contourArea(cv2.convexHull(source[chosen])) / np.prod(size)
    )
    reference_spread = float(
        cv2.contourArea(cv2.convexHull(target[chosen])) / np.prod(other_size)
    )
    count = int(chosen.sum())
    result.update(
        score=count if min(query_spread, reference_spread) >= 0.005 else 0,
        inliers=count,
        query_hull_fraction=query_spread,
        reference_hull_fraction=reference_spread,
        query_points=source[chosen].tolist(),
        reference_points=target[chosen].tolist(),
        transform=transform.tolist(),
    )
    return result


def select(ranked):
    """Use actual distinct-identity threshold logic in raw inlier-count units.

    IdentityMatch.similarity holds an integer count here, not a probability or
    neural cosine. Only the research matcher uses this representation.
    """
    return choose_identity(
        [
            IdentityMatch(row["identity_id"], row["name"], float(row["score"]))
            for row in ranked
        ],
        MIN_INLIERS,
        MIN_MARGIN,
    )


class LocalMatcher:
    def __init__(self, catalog, cache):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.contract = {
            "extractor": CONTRACT,
            "extractor_source": digest(Path(__file__).with_name("local_features.py")),
            "matcher_source": digest(Path(__file__)),
            "references": [],
        }
        self.gallery = []
        for cow in catalog.load().identities:
            for sample in cow.samples:
                image = catalog.read_image(sample)
                key = pixels_hash(image)
                self.contract["references"].append(
                    {"sample": sample, "owner": cow.id, "pixels_sha256": key}
                )
                self.gallery.append(
                    (cow.id, cow.name, sample, self.features(image, key))
                )
        self.fingerprint = hashlib.sha256(
            json.dumps(self.contract, sort_keys=True).encode()
        ).hexdigest()
        self.scores = self.cache / self.fingerprint
        self.scores.mkdir(exist_ok=True)
        self.observed = {}

    def features(self, image, key):
        contract = hashlib.sha256(
            json.dumps(CONTRACT, sort_keys=True).encode()
            + self.contract["extractor_source"].encode()
        ).hexdigest()
        path = self.cache / f"{contract}-{key}.npz"
        if path.exists():
            with np.load(path, allow_pickle=False) as data:
                return tuple(data[name] for name in ("points", "descriptors", "size"))
        points, descriptors, size = extract(image)
        np.savez_compressed(path, points=points, descriptors=descriptors, size=size)
        return points, descriptors, size

    def score(self, image):
        key = pixels_hash(image)
        path = self.scores / f"{key}.json"
        if path.exists():
            result = json.loads(path.read_text())
            if result["fingerprint"] != self.fingerprint:
                raise ValueError("Local feature cache belongs to another gallery")
        else:
            query = self.features(image, key)
            best = {}
            for owner, name, sample, reference in self.gallery:
                item = evidence(query, reference)
                if owner not in best or item["score"] > best[owner]["score"]:
                    best[owner] = {
                        **item,
                        "identity_id": owner,
                        "name": name,
                        "reference": sample,
                    }
            ranked = sorted(best.values(), key=lambda row: row["score"], reverse=True)
            result = {
                "fingerprint": self.fingerprint,
                "pixels_sha256": key,
                "keypoints": len(query[0]),
                "ranked": ranked,
                "margin": ranked[0]["score"] - ranked[1]["score"],
            }
            write_json(path, result)
            if not cv2.imwrite(str(self.scores / f"{key}.png"), image):
                raise OSError("Unable to retain public query crop")
        self.observed[key] = result
        return result
