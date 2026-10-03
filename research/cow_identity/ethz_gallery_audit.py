"""Inspect publisher identity consistency and camera-conditioned retrieval.

This is a diagnostic on already scored public regression panels. It does not
select a better model, alter enrollment, or tune acceptance thresholds.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from PIL import Image, ImageDraw, ImageOps
from scoring import metrics, score


def camera_audit(rows, vectors):
    gallery = [i for i, row in enumerate(rows) if row["panel"] == "enrollment"]
    results = {}
    videos = sorted({row["video"] for row in rows if row["panel"] != "enrollment"})
    for video in videos:
        queries = [i for i, row in enumerate(rows) if row.get("video") == video]
        query_ids = np.asarray([rows[i]["cow"] for i in queries])
        cameras = np.asarray([rows[i]["camera"] for i in queries])
        camera = str(cameras[0])
        groups = {
            "all": gallery,
            "same_camera": [i for i in gallery if rows[i]["camera"] == camera],
            "other_camera": [i for i in gallery if rows[i]["camera"] != camera],
        }
        results[video] = {}
        for name, indices in groups.items():
            ids = np.asarray([rows[i]["cow"] for i in indices])
            scores = score(vectors[indices], ids, vectors[queries], query_ids, cameras)
            result = metrics(scores, 0.65, 0.10)
            result.update(
                reference_images=len(indices),
                reference_identities=len(np.unique(ids)),
                median_top_similarity=float(np.median(scores.similarity)),
                median_margin=float(np.median(scores.margin)),
                known_rank1_by_identity={
                    str(cow): {
                        "observations": int(np.sum(query_ids == cow)),
                        "correct": int(
                            np.sum((query_ids == cow) & (scores.predicted == cow))
                        ),
                    }
                    for cow in np.unique(query_ids[scores.known])
                },
            )
            results[video][name] = result
    return results


def identity_montage(rows, cow, output):
    chosen = []
    gallery = [
        row for row in rows if row["panel"] == "enrollment" and row["cow"] == cow
    ]
    for camera in sorted({row["camera"] for row in gallery}):
        references = [row for row in gallery if row["camera"] == camera]
        for index in np.linspace(
            0, len(references) - 1, min(3, len(references))
        ).astype(int):
            row = references[index]
            chosen.append((row, f"Gallery camera {camera.split('-')[2]}"))
    for video in ("video3", "video4", "video5", "video6"):
        query = next(
            (row for row in rows if row.get("video") == video and row["cow"] == cow),
            None,
        )
        if query is not None:
            chosen.append((query, f"{video} frame {query['frame']}"))
    width, height, columns = 320, 350, 5
    canvas = Image.new(
        "RGB", (width * columns, height * ((len(chosen) + 4) // columns)), "#f4f4f4"
    )
    draw = ImageDraw.Draw(canvas)
    for i, (row, caption) in enumerate(chosen):
        x, y = (i % columns) * width, (i // columns) * height
        draw.text((x + 10, y + 10), f"Cow {cow} | {caption}", fill="black")
        path = Path(row["pixels_path"])
        if digest(path) != row["sha256"]:
            raise ValueError(f"Image changed: {path}")
        with Image.open(path) as image:
            tile = ImageOps.contain(image.convert("RGB"), (300, 300))
            canvas.paste(tile, (x + (width - tile.width) // 2, y + 45))
    canvas.save(output / f"gallery-audit-cow-{cow}.jpg", quality=90)


def evaluate(args):
    manifest_path = args.oracle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    vectors_path = args.oracle / "vectors.npz"
    if digest(vectors_path) != manifest["vectors_sha256"]:
        raise ValueError("Feature vectors changed")
    with np.load(vectors_path, allow_pickle=False) as archive:
        vectors = archive["vectors"]
    rows = manifest["rows"]
    args.output.mkdir(parents=True, exist_ok=True)
    for cow in (0, 5, 8, 10, 11, 13):
        identity_montage(rows, cow, args.output)
    report = {
        "purpose": "Post-baseline diagnostic, no retuning; camera restriction is not anatomical-view annotation and reference counts differ",
        "manifest_sha256": digest(manifest_path),
        "encoder_fingerprint": manifest["encoder_fingerprint"],
        "threshold": 0.65,
        "margin": 0.10,
        "videos": camera_audit(rows, vectors),
    }
    write_json(args.output / "camera-audit.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, default=Path(".cache/cow-ethz-oracle"))
    parser.add_argument("--output", type=Path, default=Path(".cache/cow-ethz-oracle"))
    evaluate(parser.parse_args())
