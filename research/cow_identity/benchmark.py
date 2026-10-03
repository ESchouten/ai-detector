"""Offline chronological MultiCamCows benchmark using the application encoder.

Run from the repository root; see README.md. Dataset images never leave this PC.
"""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scoring import calibrate, normalize, report, score

PROTOCOL = {
    "version": 1,
    "gallery_day": "2023Aug14",
    "query_day": "2023Aug20",
    "samples_per_camera": 3,
    "calibration_identity_fraction": 1 / 3,
    "unknown_identity_fraction": 1 / 5,
    "identity_order": "sha256('cow-identity-v1:' + identity)",
    "query_aggregation": "L2-normalized mean of three evenly spaced crop embeddings",
    "gallery_aggregation": "maximum cosine similarity over all enrolled reference crops",
    "acceptance": "similarity and distinct-identity margin; zero observed calibration false accepts",
    "conditions": ["chronological_all_cameras", "chronological_cross_camera"],
    "cross_camera": "enroll camera 1 only; query cameras 2 and 3 six days later",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def selected_images(directory: Path):
    cameras = defaultdict(list)
    for path in sorted(directory.glob("*.jpg")):
        cameras[path.stem.rsplit("_", 1)[1]].append(path)
    if set(cameras) != {"1", "2", "3"}:
        raise ValueError(f"Missing camera in {directory}")
    for camera, paths in sorted(cameras.items()):
        indices = np.linspace(0, len(paths) - 1, min(3, len(paths)), dtype=int)
        for index in indices:
            yield camera, paths[index]


def prepare(dataset: Path) -> dict:
    days = [dataset / PROTOCOL["gallery_day"], dataset / PROTOCOL["query_day"]]
    identities = set(p.name for p in days[0].iterdir() if p.is_dir()) & set(
        p.name for p in days[1].iterdir() if p.is_dir()
    )
    identities = sorted(
        identities,
        key=lambda cow: hashlib.sha256(f"cow-identity-v1:{cow}".encode()).hexdigest(),
    )
    boundary = len(identities) // 3
    if boundary < 5:
        raise ValueError(
            "Need at least 15 cows with observations on both evaluation dates"
        )
    groups = {"calibration": identities[:boundary], "test": identities[boundary:]}
    records = []
    assignments = {}
    for split, cows in groups.items():
        unknown = set(cows[: max(1, len(cows) // 5)])
        assignments[split] = {
            "known": sorted(set(cows) - unknown),
            "unknown": sorted(unknown),
        }
        for cow in sorted(cows):
            for role, day in zip(("gallery", "query"), days, strict=True):
                if role == "gallery" and cow in unknown:
                    continue
                records.extend(
                    {
                        "path": path.relative_to(dataset).as_posix(),
                        "sha256": digest(path),
                        "identity": cow,
                        "camera": camera,
                        "role": role,
                        "split": split,
                    }
                    for camera, path in selected_images(day / cow)
                )
    partitions = defaultdict(set)
    for record in records:
        partitions[record["sha256"]].add((record["split"], record["role"]))
    if any(len(partition) > 1 for partition in partitions.values()):
        raise ValueError(
            "Exact duplicate images cross gallery/query or calibration/test boundaries"
        )
    manifest = {"protocol": PROTOCOL, "identities": assignments, "images": records}
    manifest["sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    return manifest


def cache_key(image_sha: str, encoder: dict) -> str:
    return hashlib.sha256(
        json.dumps({"image": image_sha, "encoder": encoder}, sort_keys=True).encode()
    ).hexdigest()


def read_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    content = {key: value for key, value in manifest.items() if key != "sha256"}
    actual = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    if manifest["sha256"] != actual or manifest["protocol"] != PROTOCOL:
        raise ValueError("Recorded manifest content or protocol changed")
    return manifest


def load_encoder(
    model_name: str, weights: Path | None, cache: Path, device: str, image_size: int
):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))
    if model_name == "dino":
        from aidetector.adapters.inference.identity import DinoEncoder

        return DinoEncoder(cache / "models", device=device, image_size=image_size)
    from comparison_encoders import ComparisonEncoder

    if weights is None:
        raise ValueError("Comparison models need an explicit local --weights path")
    model = ComparisonEncoder(model_name, weights, device)
    if image_size != model.image_size:
        raise ValueError(f"{model_name} requires --image-size {model.image_size}")
    return model


def read_bgr(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


def embeddings(
    manifest: dict,
    dataset: Path,
    cache: Path,
    output: Path,
    image_size: int,
    device: str,
    batch_size: int,
    replay: bool,
    model_name: str = "dino",
    weights: Path | None = None,
) -> tuple[np.ndarray, dict]:
    """Content-addressed cache; replay never imports torch or opens an image."""
    started = time.perf_counter()
    encoder_file = output / "encoder.json"
    model = None
    if replay:
        encoder = json.loads(encoder_file.read_text())
        if encoder["image_size"] != image_size or encoder["name"] != model_name:
            raise ValueError(
                "Replay model/resolution differs from the recorded encoder"
            )
    else:
        model = load_encoder(model_name, weights, cache, device, image_size)
        encoder = {
            "name": model_name,
            "fingerprint": model.fingerprint,
            "image_size": image_size,
            "device": str(model.device),
            "dtype": "float32",
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("torch", "transformers", "numpy", "pillow")
            },
        }
        write_json(encoder_file, encoder)
    vectors = [None] * len(manifest["images"])
    missing = []
    cache.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(manifest["images"]):
        key = cache_key(record["sha256"], encoder)
        path = cache / f"{key}.npy"
        if path.exists():
            vectors[index] = np.load(path, allow_pickle=False)
        else:
            missing.append((index, record, path))
    if replay and missing:
        raise ValueError(
            f"Replay missing {len(missing)} embeddings; run inference explicitly"
        )
    inference_start = time.perf_counter()
    if missing:
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            images = [read_bgr(dataset / record["path"]) for _, record, _ in batch]
            for (index, _, path), vector in zip(
                batch, model.encode(images), strict=True
            ):
                vectors[index] = vector
                np.save(path, vector, allow_pickle=False)
            print(
                f"Embedded {min(offset + batch_size, len(missing))}/{len(missing)}",
                flush=True,
            )
    matrix = np.stack(vectors)
    if matrix.ndim != 2 or not np.all(np.isfinite(matrix)):
        raise ValueError("Invalid cached embeddings")
    return matrix, {
        "device": encoder["device"],
        "encoder": encoder,
        "images": len(vectors),
        "cache_hits": len(vectors) - len(missing),
        "fresh_inferences": len(missing),
        "inference_seconds": time.perf_counter() - inference_start,
        "embedding_total_seconds": time.perf_counter() - started,
    }


def collect_panel(manifest: dict, vectors: np.ndarray, condition: str, split: str):
    gallery, gallery_ids, gallery_groups = [], [], []
    query_groups = defaultdict(list)
    for item, vector in zip(manifest["images"], vectors, strict=True):
        if item["split"] != split:
            continue
        cross_camera = condition == "chronological_cross_camera"
        if item["role"] == "gallery":
            if not cross_camera or item["camera"] == "1":
                gallery.append(vector)
                gallery_ids.append(item["identity"])
                gallery_groups.append(f"{item['identity']}/{item['camera']}")
        elif not cross_camera or item["camera"] != "1":
            query_groups[(item["identity"], item["camera"])].append(vector)
    return (
        np.stack(gallery),
        np.array(gallery_ids),
        np.array(gallery_groups),
        query_groups,
    )


def evaluate(manifest: dict, vectors: np.ndarray) -> dict:
    results = {}
    for condition in PROTOCOL["conditions"]:
        panels = {}
        for split in ("calibration", "test"):
            gallery, gallery_ids, _, query_groups = collect_panel(
                manifest, vectors, condition, split
            )
            keys = sorted(query_groups)
            queries = normalize(
                np.stack([np.mean(query_groups[key], axis=0) for key in keys])
            )
            panels[split] = score(
                gallery,
                gallery_ids,
                queries,
                np.array([key[0] for key in keys]),
                np.array([key[1] for key in keys]),
            )
        threshold, margin = calibrate(panels["calibration"])
        results[condition] = {
            "threshold": threshold,
            "margin": margin,
            "calibration": report(panels["calibration"], threshold, margin),
            "test": report(panels["test"], threshold, margin),
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", required=True, type=Path, help="MultiCamCows2024Root directory"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path(".cache/cow-identity"))
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--model", choices=("dino", "miewid", "megadescriptor"), default="dino"
    )
    parser.add_argument(
        "--weights",
        type=Path,
        help="Pinned local weights for an optional comparison model",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Only read frozen manifest and embedding cache",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    manifest_path = args.output / "manifest.json"
    if args.replay:
        manifest = read_manifest(manifest_path)
    else:
        manifest = prepare(args.dataset)
        write_json(manifest_path, manifest)
    matrix, execution = embeddings(
        manifest,
        args.dataset,
        args.cache,
        args.output,
        args.image_size,
        args.device,
        args.batch_size,
        args.replay,
        args.model,
        args.weights,
    )
    results = evaluate(manifest, matrix)
    result = {
        "protocol": PROTOCOL,
        "manifest_sha256": manifest["sha256"],
        "script_sha256": {
            p.name: digest(p)
            for p in (Path(__file__), Path(__file__).with_name("scoring.py"))
        },
        "identity_counts": {
            s: {k: len(v) for k, v in g.items()}
            for s, g in manifest["identities"].items()
        },
        "results": results,
        "execution": execution,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Pre-cropped dataset images: detection, occlusion and tracking are not evaluated.",
            "Three crop embeddings are pooled per cow/day/camera; cameras are correlated.",
            "Calibration and test cows are disjoint; gallery and query dates are disjoint.",
            "Historical public data, repeatedly explored in this project; not fresh field validation.",
            "Foundation pretraining overlap is not completely auditable.",
            "Zero observed false accepts does not establish a low population error rate.",
        ],
    }
    write_json(args.output / ("replay.json" if args.replay else "report.json"), result)
    print(json.dumps({"results": results, "execution": execution}, indent=2))


if __name__ == "__main__":
    main()
