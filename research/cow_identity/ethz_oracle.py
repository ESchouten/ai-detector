"""Bounded adult-cow oracle recognition regression from a frozen ETHZ protocol.

Prepare uses sequential source-index decoding. Encode uses the application's
MIEWid and content-addressed cache. Score never trains or adjusts thresholds.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import groupby
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json
from recognition_features import crop_quality
from scoring import Scores, metrics, score

from aidetector.domain.identity import TrackAgreement, reject_conflicting_matches
from aidetector.domain.models import IdentityMatch


def source_frames(source, frames):
    capture = cv2.VideoCapture(str(source["path"]))
    try:
        if int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != source["stream_frames"]:
            raise ValueError(f"Video frame count changed: {source['video']}")
        for index in range(max(frames) + 1):
            if not capture.grab():
                raise ValueError(f"Source ended at frame {index}: {source['video']}")
            if index not in frames:
                continue
            ok, image = capture.retrieve()
            if not ok:
                raise ValueError(f"Cannot retrieve frame {index}: {source['video']}")
            yield index, capture.get(cv2.CAP_PROP_POS_MSEC), image
    finally:
        capture.release()


def prepare(args):
    protocol = json.loads(args.protocol.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    crops = args.output / "crops"
    crops.mkdir(exist_ok=True)
    rows = []
    for item in protocol["gallery"]:
        path = Path(item["path"])
        if digest(path) != item["sha256"]:
            raise ValueError(f"Gallery source changed: {path}")
        rows.append({**item, "panel": "enrollment", "pixels_path": str(path)})
    inventory = []
    for source in protocol["videos"]:
        path = Path(source["path"])
        if digest(path) != source["sha256"]:
            raise ValueError(f"Video source changed: {path}")
        labels = Path(source["labels"])
        label_indices = sorted(int(p.stem.split("_")[-1]) for p in labels.glob("*.txt"))
        if label_indices != list(range(source["stream_frames"])):
            raise ValueError(f"Non-contiguous annotation files: {labels}")
        frames = {
            index: window
            for window, (start, stop) in enumerate(source["source_index_windows"])
            for index in range(start, stop, source["sample_every_source_frames"])
        }
        for index, pts_ms, image in source_frames(source, frames):
            height, width = image.shape[:2]
            label_path = labels / f"frame_{index:06d}.txt"
            records = np.loadtxt(label_path, ndmin=2)
            centers, sizes = records[:, 1:3], records[:, 3:5]
            bounds = np.column_stack((centers - sizes / 2, centers + sizes / 2))
            bounds *= (width, height, width, height)
            boxes = bounds.clip(0, (width, height, width, height)).astype(int).tolist()
            for record, box in zip(records, boxes, strict=True):
                cow = int(record[0])
                x1, y1, x2, y2 = box
                crop = image[y1:y2, x1:x2]
                output = crops / f"{source['video']}-{index:06d}-{cow}.png"
                if not cv2.imwrite(str(output), crop):
                    raise OSError(f"Could not save {output}")
                rows.append(
                    {
                        "panel": source["role"],
                        "video": source["video"],
                        "window": frames[index],
                        "camera": source["camera"],
                        "day": source["day"],
                        "frame": index,
                        "pts_ms": pts_ms,
                        "cow": cow,
                        "box": box,
                        "label_sha256": digest(label_path),
                        "pixels_path": str(output),
                        "sha256": digest(output),
                        **crop_quality(box, boxes, width, height),
                    }
                )
        inventory.append(
            {
                "video": source["video"],
                "annotations": len(label_indices),
                "selected_frames": len(frames),
                "selected_annotations": sum(
                    row.get("video") == source["video"] for row in rows
                ),
            }
        )
        print(json.dumps(inventory[-1]), flush=True)
    write_json(
        args.output / "manifest.json",
        {
            "contract": {
                "version": 1,
                "protocol_sha256": digest(args.protocol),
                "crop": "Original normalized YOLO identity labels, integer clipped XYXY, sequential source index, lossless PNG",
                "scope": "Oracle recognition only; previously studied public data",
            },
            "rows": rows,
            "inventory": inventory,
        },
    )


def encode(args):
    from smoke_runtime import CountedEncoder

    from aidetector.adapters.inference.identity import EmbeddingCache
    from aidetector.adapters.inference.miewid import MiewidEncoder

    path = args.output / "manifest.json"
    manifest = json.loads(path.read_text())
    if manifest["contract"]["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Frozen protocol changed")
    encoder = CountedEncoder(
        MiewidEncoder(args.cache / "models", device=args.device, weights=args.weights)
    )
    cache = EmbeddingCache(args.cache / "embeddings.sqlite")
    vectors = []
    started = time.perf_counter()
    try:
        for start in range(0, len(manifest["rows"]), 8):
            images = []
            for row in manifest["rows"][start : start + 8]:
                path = Path(row["pixels_path"])
                if digest(path) != row["sha256"]:
                    raise ValueError(f"Image changed: {path}")
                image = cv2.imread(str(path))
                if image is None:
                    raise ValueError(f"Cannot decode {path}")
                images.append(image)
            vectors.extend(cache.encode(encoder, images))
    finally:
        cache.close()
    np.savez_compressed(args.output / "vectors.npz", vectors=np.asarray(vectors))
    manifest.update(
        encoder_fingerprint=encoder.fingerprint,
        device=args.device,
        vectors_sha256=digest(args.output / "vectors.npz"),
        new_encoded_images=encoder.images,
        inference_seconds=time.perf_counter() - started,
    )
    write_json(args.output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in ["device", "new_encoded_images", "inference_seconds"]
            }
        ),
        flush=True,
    )


def score_panels(args):
    manifest = json.loads((args.output / "manifest.json").read_text())
    if manifest["contract"]["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Frozen protocol changed")
    if digest(args.output / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Feature vectors changed")
    with np.load(args.output / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    rows = manifest["rows"]
    gallery = [i for i, row in enumerate(rows) if row["panel"] == "enrollment"]
    results = {}
    for video in sorted({row["video"] for row in rows if row["panel"] != "enrollment"}):
        indices = [i for i, row in enumerate(rows) if row.get("video") == video]
        selected = [rows[i] for i in indices]
        scores = score(
            vectors[gallery],
            np.asarray([rows[i]["cow"] for i in gallery]),
            vectors[indices],
            np.asarray([row["cow"] for row in selected]),
            np.asarray([row["camera"] for row in selected]),
        )
        agreement = TrackAgreement()
        accepted = np.zeros(len(selected), dtype=bool)
        for _, group in groupby(enumerate(selected), key=lambda item: item[1]["frame"]):
            frame_rows = list(group)
            candidates = []
            for i, row in frame_rows:
                eligible = (
                    row["minimum_side"] >= 64
                    and not row["clipped"]
                    and row["overlap"] <= 0.2
                )
                candidate = IdentityMatch()
                if (
                    eligible
                    and scores.similarity[i] >= 0.65
                    and scores.margin[i] >= 0.1
                ):
                    candidate = IdentityMatch(
                        str(scores.predicted[i]), similarity=float(scores.similarity[i])
                    )
                candidates.append(candidate)
            for (i, row), candidate in zip(
                frame_rows, reject_conflicting_matches(candidates), strict=True
            ):
                confirmed = agreement.update(
                    f"{video}:{row['window']}",
                    row["cow"],
                    datetime(2000, 1, 1, tzinfo=UTC)
                    + timedelta(milliseconds=row["pts_ms"]),
                    candidate,
                )
                accepted[i] = confirmed.identity_id is not None
        gated = Scores(
            scores.truth,
            scores.predicted,
            np.where(accepted, scores.similarity, -2),
            scores.margin,
            scores.known,
            scores.cameras,
        )
        results[video] = {
            "day": selected[0]["day"],
            "panel": selected[0]["panel"],
            "per_frame_oracle": metrics(scores, 0.65, 0.1),
            "production_geometry_and_oracle_agreement": metrics(gated, 0.65, 0.1),
            "per_cow_observations": dict(Counter(str(row["cow"]) for row in selected)),
        }
    summary = {
        "purpose": "Adult-cow external-scene oracle regression, no blind-test or end-to-end claim",
        "protocol_sha256": digest(args.protocol),
        "manifest_sha256": digest(args.output / "manifest.json"),
        "gallery_per_cow": dict(Counter(str(rows[i]["cow"]) for i in gallery)),
        "encoder_fingerprint": manifest["encoder_fingerprint"],
        "device": manifest["device"],
        "inference_seconds": manifest["inference_seconds"],
        "new_encoded_images": manifest["new_encoded_images"],
        "threshold": 0.65,
        "margin": 0.1,
        "videos": results,
    }
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "encode", "score"))
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("research/cow_identity/ethz_protocol.json"),
    )
    parser.add_argument("--output", type=Path, default=Path(".cache/cow-ethz-oracle"))
    parser.add_argument(
        "--cache", type=Path, default=Path(".cache/cow-ethz-oracle-cache")
    )
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    {"prepare": prepare, "encode": encode, "score": score_panels}[args.stage](args)
