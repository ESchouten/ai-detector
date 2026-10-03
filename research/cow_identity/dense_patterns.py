"""Compare cached foreground MIEW patches with the original global descriptor."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json
from local_feature_fusion import calibrate_fusion, subset
from recognition_experiment import select_gallery
from recognition_fusion import observation_key
from scoring import Scores, metrics, normalize
from video_assessment import pixels_hash

from aidetector.adapters.inference.miewid import MiewidEncoder

PROTOCOL = Path(__file__).with_name("dense_pattern_protocol.json")


def reciprocal_score(similarities, first_positions, second_positions):
    """Reject one-way repeated-pattern matches and tiny concentrated support."""
    if min(similarities.shape) < 4:
        return 0.0
    nearest = similarities.argmax(axis=1)
    reverse = similarities.argmax(axis=0)
    rows = np.flatnonzero(reverse[nearest] == np.arange(len(nearest)))
    columns = nearest[rows]
    if len(rows) < 4:
        return 0.0
    for points in (first_positions[rows], second_positions[columns]):
        quadrants = (points[:, 0] >= 0.5) * 2 + (points[:, 1] >= 0.5)
        if len(np.unique(quadrants)) < 2:
            return 0.0
    return float(np.sort(similarities[rows, columns])[-8:].mean())


def extract(encoder, path, expected_pixels, cache, fingerprint):
    key = hashlib.sha256(f"{fingerprint}:{expected_pixels}".encode()).hexdigest()
    target = cache / f"{key}.npz"
    if target.exists():
        with np.load(target, allow_pickle=False) as arrays:
            return arrays["patches"], arrays["positions"]
    image = cv2.imread(str(path))
    if image is None or pixels_hash(image) != expected_pixels:
        raise ValueError("Foreground crop differs from its recorded pixels")
    tensor = encoder.transform(Image.fromarray(image[:, :, ::-1]))[None]
    with torch.inference_mode():
        values = encoder.model.backbone.forward_features(tensor.to(encoder.device))
        values = values[0].permute(1, 2, 0).cpu().numpy()
    height, width = values.shape[:2]
    foreground = np.any(image != 127, axis=2).astype(np.float32)
    keep = cv2.resize(foreground, (width, height), interpolation=cv2.INTER_AREA) >= 0.75
    y, x = np.mgrid[:height, :width]
    positions = np.stack([(y + 0.5) / height, (x + 0.5) / width], axis=-1)[keep]
    patches = values[keep]
    np.savez_compressed(target, patches=patches, positions=positions)
    return patches, positions


def evaluate(pair_scores, global_scores, owners, rows, queries):
    truth = np.array([rows[i]["cow"] for i in queries])
    panels = np.array([rows[i]["panel"] for i in queries])
    results = []
    for weight in json.loads(PROTOCOL.read_text())["global_blends"]:
        combined = (1 - weight) * global_scores + weight * pair_scores
        identities = np.unique(owners)
        values = np.stack(
            [combined[:, owners == cow].max(1) for cow in identities], axis=1
        )
        order = np.argsort(-values, axis=1, kind="stable")
        index = np.arange(len(queries))
        best = values[index, order[:, 0]]
        scores = Scores(
            truth,
            identities[order[:, 0]],
            best,
            best - values[index, order[:, 1]],
            np.isin(truth, identities),
            panels,
        )
        hits, threshold, margin = calibrate_fusion(
            subset(scores, panels == "calibration"), 1
        )
        results.append(
            {
                "local_weight": weight,
                "calibration_choice": [hits, threshold, margin],
                "panels": {
                    panel: metrics(subset(scores, panels == panel), threshold, margin)
                    for panel in sorted(set(panels))
                },
            }
        )
    return results


def run(args):
    torch.set_num_threads(2)
    manifest = json.loads((args.features / "manifest.json").read_text())
    crops = json.loads((args.crops / "crops.json").read_text())
    source_hash = digest(args.features / "manifest.json")
    if crops["contract"]["source_manifest_sha256"] != source_hash:
        raise ValueError("Crop and feature source manifests differ")
    if digest(args.features / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Global feature array changed")
    with np.load(args.features / "vectors.npz", allow_pickle=False) as arrays:
        vectors = arrays["vectors"]
    protocol = json.loads(PROTOCOL.read_text())
    rows = manifest["rows"]
    gallery = select_gallery(rows, vectors, "diverse10")
    seconds = {
        panel: set(range(first, last + 1, step))
        for panel, (first, last, step) in protocol["query_seconds"].items()
    }
    queries = np.array(
        [
            i
            for i, row in enumerate(rows)
            if row["second"] in seconds.get(row["panel"], set())
        ]
    )
    # Original crop pixels, rather than truth identity, join the image archives.
    lookup = {observation_key(row): row for row in crops["rows"]}
    if len(lookup) != len(crops["rows"]):
        raise ValueError("Foreground archive contains duplicate observations")
    encoder = MiewidEncoder(args.output / "models", args.device, args.weights)
    contract = {
        "protocol_sha256": digest(PROTOCOL),
        "encoder": encoder.fingerprint,
        "crop_contract": crops["contract"],
        "device": args.device,
        "torch": torch.__version__,
        "opencv": cv2.__version__,
    }
    fingerprint = hashlib.sha256(
        json.dumps(contract, sort_keys=True).encode()
    ).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "patches"
    cache.mkdir(exist_ok=True)
    started = time.perf_counter()
    patches = {}
    for number, index in enumerate(sorted(set(gallery) | set(queries))):
        image = lookup[observation_key(rows[index])]["variants"]["masked"]
        patches[index] = extract(
            encoder,
            args.crops / image["path"],
            image["pixels_sha256"],
            cache,
            fingerprint,
        )
        if number % 50 == 0:
            print(
                json.dumps(
                    {"images": number + 1, "seconds": time.perf_counter() - started}
                ),
                flush=True,
            )
    extraction_seconds = time.perf_counter() - started
    mean = np.concatenate([patches[index][0] for index in gallery]).mean(0)
    centered = {
        index: (normalize(values - mean), positions)
        for index, (values, positions) in patches.items()
    }
    pair_scores = np.zeros((len(queries), len(gallery)), np.float32)
    # Torch limits matching to two CPU threads even on machines with threaded BLAS.
    with torch.inference_mode():
        for i, query in enumerate(queries):
            first, first_positions = centered[query]
            for j, reference in enumerate(gallery):
                second, second_positions = centered[reference]
                similarities = (
                    torch.from_numpy(first) @ torch.from_numpy(second).T
                ).numpy()
                pair_scores[i, j] = reciprocal_score(
                    similarities, first_positions, second_positions
                )
    np.savez_compressed(
        args.output / "scores.npz", gallery=gallery, queries=queries, scores=pair_scores
    )
    owners = np.array([rows[i]["cow"] for i in gallery])
    report = {
        "script_sha256": digest(Path(__file__)),
        "contract": contract,
        "input_manifest_sha256": source_hash,
        "scores_sha256": digest(args.output / "scores.npz"),
        "gallery": gallery.tolist(),
        "queries": queries.tolist(),
        "extraction_seconds": extraction_seconds,
        "total_seconds": time.perf_counter() - started,
        "variants": evaluate(
            pair_scores, vectors[queries] @ vectors[gallery].T, owners, rows, queries
        ),
    }
    write_json(args.output / "report.json", report)
    print(json.dumps(report["variants"]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("features", "crops", "weights", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
