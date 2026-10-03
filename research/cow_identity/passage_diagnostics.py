"""Explain the frozen passage outcome from existing pixels and cached vectors only."""

import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_metrics import full_frame_boxes, rates, score_frame
from passage_runtime import MANIFEST, sampled_frames
from video_assessment import pair_boxes

from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.domain.models import BoundingBox

ROOT = Path(".cache/cow-passage-query-preset-5fps")
FREEZE = Path(__file__).with_name("passage_query_freeze.json")


def vector(database, fingerprint, image):
    key = EmbeddingCache.key(fingerprint, image)
    row = database.execute(
        "SELECT vector FROM embeddings WHERE key=?", (key,)
    ).fetchone()
    if row is None:
        raise ValueError(
            "An expected frozen runtime embedding is missing; no inference permitted"
        )
    return EmbeddingCache._read_vector(row[0], 2152)


def describe_scores(image, boxes, policy, database, fingerprint, gallery, owners):
    classes = np.unique(owners)
    height, width = image.shape[:2]
    result = []
    for box in boxes:
        eligible = usable_crop(
            box,
            tuple(boxes),
            width,
            height,
            policy["min_crop_size"],
            policy["max_overlap"],
        )
        item = {
            "eligible": eligible,
            "best": None,
            "similarity": None,
            "margin": None,
            "candidate": None,
        }
        if eligible:
            crop = image[box.y1 : box.y2, box.x1 : box.x2]
            similarities = vector(database, fingerprint, crop) @ gallery.T
            scores = np.array([similarities[owners == cow].max() for cow in classes])
            order = np.argsort(-scores, kind="stable")
            score, margin = (
                float(scores[order[0]]),
                float(scores[order[0]] - scores[order[1]]),
            )
            best = int(classes[order[0]])
            item.update(best=best, similarity=score, margin=margin)
            if score >= policy["min_similarity"] and margin >= policy["min_margin"]:
                item["candidate"] = best
        result.append(item)
    return result


def truth_group(row, principal):
    if row["cow"] != principal:
        return "nuisance"
    box = row["box"]
    if row["uncertain"]:
        return "uncertain_principal"
    if box[0] <= 1 or box[1] <= 1 or box[2] >= 1919 or box[3] >= 1079:
        return "definite_border_principal"
    return "definite_nonborder_principal"


def cached_gallery(database, fingerprint, catalog_path):
    catalog = json.loads((catalog_path / "catalog.json").read_text())
    gallery, owners = [], []
    for cow in catalog["identities"]:
        for sample in cow["samples"]:
            image = cv2.imread(str(catalog_path / "images" / f"{sample}.jpg"))
            gallery.append(vector(database, fingerprint, image))
            owners.append(int(cow["id"], 16))
    return np.stack(gallery), np.array(owners)


def run():
    freeze = json.loads(FREEZE.read_text())
    protocol = json.loads(Path(freeze["protocol"]).read_text())
    predictions = json.loads((ROOT / "predictions.json").read_text())
    annotations = json.loads(Path(freeze["annotations"]).read_text())
    source = json.loads(MANIFEST.read_text())
    catalog_path = Path(freeze["gallery"])
    known = set(protocol["known_cows"])
    fingerprint = predictions["encoder_fingerprint"]
    truth = {(row["clip"], row["frame"]): row for row in annotations["frames"]}
    stages = {
        name: Counter()
        for name in (
            "eligible_rank1",
            "single_observation_threshold",
            "actual_three_observation_policy",
        )
    }
    groups = {}
    timeline = []
    overall = Counter()
    with sqlite3.connect(
        f"file:{ROOT / 'query-embeddings.sqlite'}?mode=ro", uri=True
    ) as database:
        gallery, owners = cached_gallery(database, fingerprint, catalog_path)
        for predicted_clip in predictions["clips"]:
            clip = next(
                row for row in source["clips"] if row["clip"] == predicted_clip["clip"]
            )
            sample = {
                **clip,
                "sampled_local_frame_indices": [
                    frame["local_frame"] for frame in predicted_clip["timeline"]
                ],
            }
            path = ROOT / "clips" / clip["clip"] / "source.avi"
            if digest(path) != clip["sha256"]:
                raise ValueError("Frozen query video changed")
            for (index, image), frame in zip(
                sampled_frames(sample, path, protocol["detector"]["frames_width"]),
                predicted_clip["timeline"],
                strict=True,
            ):
                boxes = [
                    BoundingBox(
                        **{
                            key: value
                            for key, value in box.items()
                            if key != "identity"
                        }
                    )
                    for box in frame["boxes"]
                ]
                scores = describe_scores(
                    image,
                    boxes,
                    protocol["identity_policy"],
                    database,
                    fingerprint,
                    gallery,
                    owners,
                )
                overall.update(
                    {
                        "processing_frames": 1,
                        "detected_boxes": len(boxes),
                        "eligible_boxes": sum(item["eligible"] for item in scores),
                        "single_observation_candidates": sum(
                            item["candidate"] is not None for item in scores
                        ),
                        "actual_names": sum(
                            bool(box["identity"]["identity_id"])
                            for box in frame["boxes"]
                        ),
                    }
                )
                annotation = truth.get((clip["clip"], index))
                if annotation is None:
                    continue
                pairs = pair_boxes(
                    full_frame_boxes(frame, clip["width"], clip["height"]),
                    annotation["boxes"],
                )
                reverse = {j: i for i, j in pairs.items()}
                for j, row in enumerate(annotation["boxes"]):
                    key = truth_group(row, annotation["principal_cow"])
                    count = groups.setdefault(key, Counter())
                    count["visible"] += 1
                    i = reverse.get(j)
                    count["detected"] += int(i is not None)
                    count["eligible"] += int(i is not None and scores[i]["eligible"])
                for stage, field in (
                    ("eligible_rank1", "best"),
                    ("single_observation_threshold", "candidate"),
                ):
                    variant = copy.deepcopy(frame)
                    for box, item in zip(variant["boxes"], scores, strict=True):
                        name = item[field]
                        box["identity"]["identity_id"] = (
                            f"{name:032x}" if name is not None else None
                        )
                    counts, _ = score_frame(variant, annotation, known)
                    stages[stage].update(counts)
                counts, _ = score_frame(frame, annotation, known)
                stages["actual_three_observation_policy"].update(counts)
                timeline.append(
                    {
                        "clip": clip["clip"],
                        "frame": index,
                        "second": frame["second"],
                        "scores": scores,
                        "actual_boxes": frame["boxes"],
                    }
                )
    output = {
        "status": "Post-result diagnostic; no new inference, fitting, threshold changes or June9 claim of a new blind evaluation",
        "freeze_sha256": digest(FREEZE),
        "predictions_sha256": digest(ROOT / "predictions.json"),
        "processing_counts": dict(overall),
        "scored_stages": {key: rates(value) for key, value in stages.items()},
        "annotation_groups": {key: dict(value) for key, value in groups.items()},
        "group_definition": "Definite nonborder principal means independently marked not uncertain and annotated rectangle does not touch native image boundary; this is a visibility proxy, not a guarantee of no occlusion. Nuisance included in official main result.",
        "timeline": timeline,
    }
    path = Path(__file__).parent / "results/2026-10-03/purdue-passage-diagnostics.json"
    write_json(path, output)
    print(
        json.dumps({key: value for key, value in output.items() if key != "timeline"})
    )


if __name__ == "__main__":
    run()
