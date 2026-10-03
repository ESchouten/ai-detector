"""Read-only coat/reference comparison after the frozen passage result."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_diagnostics import cached_gallery, vector
from passage_runtime import MANIFEST, sampled_frames
from passage_torso import associate_torsos
from passage_torso_diagnostics import clean_box
from PIL import Image, ImageDraw, ImageOps

BASE = Path(".cache/cow-passage-query-torso")
CACHE = Path(".cache/cow-passage-query-torso-border/query-embeddings.sqlite")
GALLERY = Path(".cache/cow-passage-gallery-torso")
DIAGNOSTIC = (
    Path(__file__).parent / "results/2026-10-03/purdue-torso-border-diagnostics.json"
)
OUTPUT = Path(".cache/cow-passage-crop-audit")


def tile(image, lines):
    canvas = Image.new("RGB", (260, 280), "white")
    rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    canvas.paste(ImageOps.pad(rgb, (250, 215), color="#dddddd"), (5, 5))
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        draw.text((5, 225 + index * 16), line, fill="black")
    return canvas


def inspect(
    clip, frame, image, manifest, database, fingerprint, gallery, owners, samples
):
    raw = [clean_box(box) for box in frame["raw_detector_boxes"]]
    whole = [box for box in raw if box.label == "whole_visible_cow"]
    torsos = [box for box in raw if box.label == "coat_torso"]
    associated = dict(associate_torsos(whole, torsos))
    records = []
    for truth in manifest["matched_truth"]:
        index, cow = truth["prediction_index"], truth["cow"]
        if index is None or index not in associated:
            continue
        box = associated[index]
        crop = image[box.y1 : box.y2, box.x1 : box.x2]
        scores = vector(database, fingerprint, crop) @ gallery.T
        own = np.flatnonzero(owners == cow)
        rival = np.flatnonzero(owners != cow)
        own_index = int(own[np.argmax(scores[own])]) if len(own) else None
        rival_index = int(rival[np.argmax(scores[rival])])
        items = [
            (
                crop,
                [
                    f"cow {cow}; second {frame['second']:g}",
                    f"torso {box.x2 - box.x1}x{box.y2 - box.y1}; edge {box.x1 <= 0 or box.x2 >= image.shape[1] - 1}",
                ],
            )
        ]
        for label, selected in (
            ("same cow reference", own_index),
            ("closest different cow", rival_index),
        ):
            reference = (
                cv2.imread(str(GALLERY / "images" / f"{samples[selected]}.jpg"))
                if selected is not None
                else np.zeros((100, 100, 3), np.uint8)
            )
            items.append(
                (
                    reference,
                    [
                        label,
                        f"{int(owners[selected])}; cosine {scores[selected]:.3f}"
                        if selected is not None
                        else "no enrolled reference",
                    ],
                )
            )
        row_image = Image.new("RGB", (780, 280), "white")
        for column, (pixels, lines) in enumerate(items):
            row_image.paste(tile(pixels, lines), (260 * column, 0))
        records.append(
            (
                {
                    "clip": clip["clip"],
                    "frame": frame["local_frame"],
                    "second": frame["second"],
                    "cow": cow,
                    "torso_box": [box.x1, box.y1, box.x2, box.y2],
                    "whole_box": [
                        whole[index].x1,
                        whole[index].y1,
                        whole[index].x2,
                        whole[index].y2,
                    ],
                    "touches_boundary": box.x1 < 1
                    or box.y1 < 1
                    or box.x2 >= image.shape[1] - 1
                    or box.y2 >= image.shape[0] - 1,
                    "same_cow_similarity": float(scores[own_index])
                    if own_index is not None
                    else None,
                    "rival_similarity": float(scores[rival_index]),
                    "rival_cow": int(owners[rival_index]),
                    "same_cow_reference": samples[own_index]
                    if own_index is not None
                    else None,
                    "rival_reference": samples[rival_index],
                    "same_cow_margin": float(scores[own_index] - scores[rival_index])
                    if own_index is not None
                    else None,
                    "production_scores": manifest["scores"][index],
                },
                row_image,
            )
        )
    return records


def run():
    predictions = json.loads((BASE / "predictions.json").read_text())
    diagnostic = json.loads(DIAGNOSTIC.read_text())
    if diagnostic["predictions_sha256"] != digest(CACHE.parent / "border_only.json"):
        raise ValueError("Diagnostic belongs to another border outcome")
    source = json.loads(MANIFEST.read_text())
    catalog = json.loads((GALLERY / "catalog.json").read_text())
    samples = [sample for cow in catalog["identities"] for sample in cow["samples"]]
    scored = {
        (row["clip"], row["frame"]): row
        for row in diagnostic["timeline"]
        if row["scored"]
    }
    grouped = defaultdict(list)
    with (
        sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True) as database,
        sqlite3.connect(
            f"file:{BASE / 'gallery-embeddings.sqlite'}?mode=ro", uri=True
        ) as gallery_database,
    ):
        fingerprint = predictions["encoder_fingerprint"]
        gallery, owners = cached_gallery(gallery_database, fingerprint, GALLERY)
        for predicted in predictions["clips"]:
            clip = next(
                row for row in source["clips"] if row["clip"] == predicted["clip"]
            )
            path = BASE / "clips" / clip["clip"] / "source.avi"
            if digest(path) != clip["sha256"]:
                raise ValueError("Query source changed")
            frames = {row["local_frame"]: row for row in predicted["timeline"]}
            for index, image in sampled_frames(clip, path, 1280):
                records = inspect(
                    clip,
                    frames[index],
                    image,
                    scored[(clip["clip"], index)],
                    database,
                    fingerprint,
                    gallery,
                    owners,
                    samples,
                )
                for record, row_image in records:
                    grouped[record["cow"]].append((record, row_image))
    OUTPUT.mkdir(exist_ok=True)
    records = []
    for cow, rows in grouped.items():
        sheet = Image.new("RGB", (780, 280 * len(rows)), "white")
        for index, (record, row_image) in enumerate(rows):
            sheet.paste(row_image, (0, 280 * index))
            records.append(record)
        sheet.save(OUTPUT / f"cow-{cow}.jpg")
    result = {
        "diagnostic_sha256": digest(DIAGNOSTIC),
        "source_sha256": digest(Path(__file__)),
        "status": "After-result cache-only qualitative diagnostic; ground truth selects same-cow comparison only for analysis, never used in inference. No new matching policy or accuracy claims.",
        "records": records,
    }
    write_json(OUTPUT / "manifest.json", result)
    write_json(
        Path(__file__).parent / "results/2026-10-03/purdue-torso-crop-audit.json",
        result,
    )
    print(json.dumps({"records": len(records), "sheets": list(grouped)}))


if __name__ == "__main__":
    run()
