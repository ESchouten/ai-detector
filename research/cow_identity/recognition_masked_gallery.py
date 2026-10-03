"""Package unanimous photo reviews and encode their exact foreground pixels once."""

import argparse
import importlib.metadata
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/recognition"
PILOT = Path(".cache/cow-masked-reference-pilot-v2/manifest.json")
REMAINING = Path(".cache/cow-masked-reference-remaining/manifest.json")
FINGERPRINT = "af1f90d85f31b9e5721a3606eb990adcb3807626aab573dbe202b51260533d0a"
WEIGHTS = Path.home() / (
    ".cache/huggingface/hub/models--conservationxlabs--miewid-msv3/blobs/"
    "adff92b39678f37eb74861c6399a741639a8907ec2382738e903d6120727b348"
)
CROP = "Exact reviewed PNG: tight largest8-connected foreground, other pixels127; BGR decode, no alignment, padding or new crop selection."


def decisions(review):
    rows = review.get("rows", review.get("decisions"))
    result = {}
    for row in rows:
        candidate = row["candidate"]
        accepted = row.get("accepted", row.get("decision") == "accept")
        cow = row["cow"]
        if candidate in result or (accepted and cow not in range(1, 7)):
            raise ValueError("Duplicate question or invalid accepted biological ID")
        result[candidate] = {"accepted": accepted, "cow": cow, "review": row}
    return result


def consensus(reviews, expected):
    """Any uncertainty or disagreement rejects; never derive a name from its slot."""
    mapped = {name: decisions(review) for name, review in reviews.items()}
    if len(mapped) < 2 or any(set(rows) != set(expected) for rows in mapped.values()):
        raise ValueError("Every independent reviewer must cover every question")
    output = []
    for candidate in sorted(expected):
        votes = {name: rows[candidate] for name, rows in mapped.items()}
        cows = {row["cow"] for row in votes.values()}
        accepted = all(row["accepted"] for row in votes.values()) and len(cows) == 1
        output.append(
            {
                "candidate": candidate,
                "accepted": accepted,
                "cow": next(iter(cows)) if accepted else None,
                "reviews": votes,
            }
        )
    return output


def checked_photos(rows):
    files = {}
    for row in rows:
        for kind in ("foreground", "context", "marked_context"):
            image = row[kind]
            path = Path(image["path"])
            if digest(path) != image["sha256"]:
                raise ValueError("A frozen review photo changed")
            files[str(path)] = image["sha256"]
    return files


def review_inputs():
    files = [PILOT, REMAINING]
    results = []
    for scope, reviewers, expected in (
        ("pilot", ("root", "cattle", "audit"), range(12)),
        ("remaining", ("cattle", "audit"), range(12, 52)),
    ):
        paths = {
            name: RESULTS / f"masked-reference-{scope}-review-{name}.json"
            for name in reviewers
        }
        files.extend(paths.values())
        reviews = {name: json.loads(path.read_text()) for name, path in paths.items()}
        results.extend(consensus(reviews, expected))
    return files, results


def package(output):
    files, questions = review_inputs()
    rendered = (
        json.loads(PILOT.read_text())["rows"]
        + json.loads(REMAINING.read_text())["rows"]
    )
    initial = sorted(
        (r for r in rendered if "candidate" not in r), key=lambda r: r["track_id"]
    )
    if [row["track_id"] for row in initial] != list(range(6)) or any(
        row["second"] != 0 for row in initial
    ):
        raise ValueError("Retain the six already confirmed initial references")
    photos = {r["candidate"]: r for r in rendered if "candidate" in r}
    if len(rendered) != 58 or set(photos) != set(range(52)):
        raise ValueError("Preserve all frozen questions without replacement")
    rows = [
        dict(row, cow=row["track_id"] + 1, review_basis="initial_confirmed")
        for row in initial
    ]
    rows.extend(
        dict(
            photos[q["candidate"]], cow=q["cow"], review_basis="unanimous_photo_review"
        )
        for q in questions
        if q["accepted"]
    )
    counts = Counter(row["cow"] for row in rows)
    if counts != {1: 10, 2: 10, 3: 2, 4: 2, 5: 5, 6: 10}:
        raise ValueError("Final authorized conservative intersection differs")
    files.extend(
        [
            Path(__file__),
            ROOT / "test_recognition_masked_gallery.py",
            ROOT / "recognition_masked_pilot_v2_protocol.json",
            ROOT / "recognition_masked_remaining_protocol.json",
            RESULTS / "masked-reference-pilot-v2-selection.json",
            RESULTS / "masked-reference-pilot-v2-render.json",
            RESULTS / "masked-reference-remaining-render.json",
            RESULTS / "masked-reference-environment-audit.json",
            Path(".cache/cow-cutie/actual-seed-masks/manifest.json"),
        ]
    )
    write_json(
        output,
        {
            "status": "FROZEN_REVIEWED_REFERENCES_NOT_ENCODED",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "files": {**{str(p): digest(p) for p in files}, **checked_photos(rendered)},
            "rows": rows,
            "questions": questions,
            "counts": {
                "initial_already_confirmed": 6,
                "new_unique_questions": 52,
                "new_accepted": 33,
                "new_uncertain_or_disagreed": 19,
                "references": len(rows),
                "references_per_cow": dict(counts),
            },
            "crop": CROP,
            "decision": "All reviewers accept the identical biological ID; every uncertainty/disagreement rejects. No majority override, backfill or inherited suggested slot labels.",
            "limits": "AI reviewers knew the scene; this is not independently blinded farmer truth. Actual-proposal-seeded early0..629 references, with training-frame optimism. Historical query masks used publisher-box initialization. Six initial photos add no new naming question;52new photos required multiple AI judgements.",
        },
    )


def libraries():
    return {
        key: importlib.metadata.version(key)
        for key in ("torch", "torchvision", "timm", "Pillow", "numpy", "safetensors")
    }


def freeze(package_path, output):
    value = verify(package_path)
    sources = [
        package_path,
        Path(__file__),
        ROOT / "test_recognition_masked_gallery.py",
        ROOT / "benchmark.py",
        ROOT / "video_assessment.py",
        WEIGHTS,
    ]
    sources.extend(
        Path("detector/src/aidetector/adapters/inference") / name
        for name in ("miewid.py", "identity.py", "device.py")
    )
    write_json(
        output,
        {
            "status": "FROZEN_REFERENCE_ENCODING_ONLY",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {**value["files"], **{str(p): digest(p) for p in sources}},
            "package": str(package_path),
            "weights": str(WEIGHTS),
            "model": "conservationxlabs/miewid-msv3",
            "revision": "4f1d7f2b521149e5fe34bb85f377248ce9971a7d",
            "encoder_fingerprint": FINGERPRINT,
            "device": "mps",
            "precision": "float32",
            "libraries": libraries(),
            "opencv": cv2.__version__,
            "crop": CROP,
            "batch_size": 8,
            "threads": 2,
            "operations": "Only39 reviewed PNGs through local pinned MiewidEncoder; SQLite cache keyed by actual pixels+encoder fingerprint. No remote code/download, training, augmentation, query inference/scoring or threshold selection.",
        },
    )


def verify(path):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    return value


def encode_batches(encoder, cache, rows):
    vectors = []
    for start in range(0, len(rows), 8):
        images = []
        for row in rows[start : start + 8]:
            image = cv2.imread(row["foreground"]["path"], cv2.IMREAD_COLOR)
            if (
                image is None
                or pixels_hash(image) != row["foreground"]["pixels_sha256"]
            ):
                raise ValueError("Decoded foreground pixels differ from reviewed crop")
            images.append(image)
        vectors.extend(cache.encode(encoder, images))
        print(
            f"Encoded {min(start + 8, len(rows))}/{len(rows)} reviewed references",
            flush=True,
        )
    return np.asarray(vectors, dtype=np.float32)


def encode(protocol_path, output):
    protocol = verify(protocol_path)
    if protocol["libraries"] != libraries() or protocol["opencv"] != cv2.__version__:
        raise ValueError("Installed encoding libraries changed")
    import torch

    from aidetector.adapters.inference.identity import EmbeddingCache
    from aidetector.adapters.inference.miewid import MiewidEncoder

    if not torch.backends.mps.is_available():
        raise RuntimeError("This frozen encoding requires actual MPS")
    torch.set_num_threads(protocol["threads"])
    package_value = json.loads(Path(protocol["package"]).read_text())
    started = time.monotonic()
    encoder = MiewidEncoder(output / "models", "mps", Path(protocol["weights"]))
    if encoder.fingerprint != protocol["encoder_fingerprint"]:
        raise ValueError(
            "Constructed encoder differs from historical query fingerprint"
        )
    output.mkdir(parents=True, exist_ok=False)
    cache = EmbeddingCache(output / "embeddings.sqlite")
    try:
        vectors = encode_batches(encoder, cache, package_value["rows"])
    finally:
        cache.close()
    torch.mps.synchronize()
    if (
        vectors.shape != (39, 2152)
        or not np.isfinite(vectors).all()
        or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=0.001)
    ):
        raise ValueError("Expected39finite normalized MIEW vectors")
    np.savez_compressed(output / "vectors.npz", vectors=vectors)
    write_json(
        output / "manifest.json",
        {
            "contract": {
                "protocol_sha256": digest(protocol_path),
                "package_sha256": digest(Path(protocol["package"])),
                "representation": {
                    "encoder_fingerprint": encoder.fingerprint,
                    "crop": CROP,
                },
                "encoder_fingerprint": encoder.fingerprint,
                "device": encoder.device,
                "precision": "float32",
                "libraries": libraries(),
            },
            "rows": package_value["rows"],
            "vectors_sha256": digest(output / "vectors.npz"),
            "counts": package_value["counts"],
            "elapsed_seconds": time.monotonic() - started,
            "mps_active_bytes_after": torch.mps.current_allocated_memory(),
            "mps_driver_bytes_after": torch.mps.driver_allocated_memory(),
            "limits": package_value["limits"],
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("package", "freeze", "encode"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or (args.mode != "package" and args.input is None):
        parser.error("Use a new output and provide the frozen input for freeze/encode")
    if args.mode == "package":
        package(args.output)
    elif args.mode == "freeze":
        freeze(args.input, args.output)
    else:
        encode(args.input, args.output)
