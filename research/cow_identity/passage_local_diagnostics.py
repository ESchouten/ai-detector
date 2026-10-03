"""Inspect fixed RootSIFT outcomes without recomputing or changing decisions."""

import copy
import json
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from local_features import extract
from passage_local_match import select
from passage_local_query import FREEZE, OUTPUT
from passage_metrics import full_frame_boxes, rates, score_frame
from passage_torso import associate_torsos
from PIL import Image, ImageDraw, ImageOps
from video_assessment import pair_boxes

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.domain.models import BoundingBox, IdentityMatch

REPORT = Path(__file__).parent / "results/2026-10-03/purdue-local-diagnostics.json"


def matched_crops(frame):
    raw = tuple(
        BoundingBox(**{key: value for key, value in row.items() if key != "identity"})
        for row in frame["raw_detector_boxes"]
    )
    whole = tuple(box for box in raw if box.label == "whole_visible_cow")
    torsos = tuple(box for box in raw if box.label == "coat_torso")
    pairs = associate_torsos(whole, torsos)
    shifted = tuple(
        replace(box, x1=box.x1 + 2, x2=box.x2 + 2, y1=box.y1 + 2, y2=box.y2 + 2)
        for _, box in pairs
    )
    owners = [
        owner
        for (owner, _), box in zip(pairs, shifted, strict=True)
        if usable_crop(box, shifted, frame["width"] + 4, frame["height"] + 4, 64, 0.2)
    ]
    if len(owners) != len(frame["local_crops"]):
        raise ValueError("Sampled crop order differs from saved geometry")
    return dict(zip(owners, frame["local_crops"], strict=True))


def montage(rows, gallery, cache):
    directory = OUTPUT / "diagnostics"
    directory.mkdir(exist_ok=True)
    for cow in sorted({str(row["truth"]) for row in rows}):
        selected = [row for row in rows if str(row["truth"]) == cow]
        sheet = Image.new("RGB", (700, 280 * len(selected)), "white")
        for index, row in enumerate(selected):
            record, y = row["best"], index * 280
            draw = ImageDraw.Draw(sheet)
            draw.text(
                (10, y + 5),
                f"truth {cow}; frame {row['frame']}; best {record['name']}; inliers {record['score']}; margin {row['margin']}",
                fill="black",
            )
            draw.text(
                (10, y + 24),
                f"keypoints {row['keypoints']}; support {record['query_hull_fraction']:.3f}/{record['reference_hull_fraction']:.3f}; accepted {row['accepted']}",
                fill="black",
            )
            paths = (
                cache / f"{row['pixels_sha256']}.png",
                gallery / "images" / f"{record['reference']}.jpg",
            )
            placements = []
            for column, path in enumerate(paths):
                image = Image.open(path).convert("RGB")
                image = ImageOps.contain(image, (320, 215))
                at = (10 + column * 350, y + 50)
                sheet.paste(image, at)
                placements.append((at, image.size))
            draw = ImageDraw.Draw(sheet)
            for q, r in zip(
                record["query_points"], record["reference_points"], strict=True
            ):
                points = []
                for coords, (at, size), dims in zip(
                    (q, r),
                    placements,
                    (record["query_size"], record["reference_size"]),
                    strict=True,
                ):
                    points.append(
                        (
                            at[0] + coords[0] * size[0] / dims[1],
                            at[1] + coords[1] * size[1] / dims[0],
                        )
                    )
                draw.line(points, fill=(0, 190, 95), width=1)
                for x, yy in points:
                    draw.ellipse((x - 2, yy - 2, x + 2, yy + 2), fill=(245, 90, 0))
        sheet.save(directory / f"cow-{cow}.jpg")


def main():
    freeze = json.loads(FREEZE.read_text())
    evidence = json.loads((OUTPUT / "evidence.json").read_text())
    predictions = json.loads((OUTPUT / "local_border.json").read_text())
    annotations = json.loads(Path(freeze["annotations"]).read_text())
    if evidence["protocol_sha256"] != digest(FREEZE) or predictions[
        "followup_freeze_sha256"
    ] != digest(FREEZE):
        raise ValueError("Evidence comes from another frozen control")
    protocol = json.loads(Path(freeze["protocol"]).read_text())
    known = set(protocol["known_cows"])
    timelines = {
        (clip["clip"], frame["local_frame"]): frame
        for clip in predictions["clips"]
        for frame in clip["timeline"]
    }
    stages = {
        key: Counter() for key in ("positive_unique_rank1", "single_sample_inlier_rule")
    }
    records, per_cow = [], defaultdict(Counter)
    for annotation in annotations["frames"]:
        frame = timelines[annotation["clip"], annotation["frame"]]
        owners = matched_crops(frame)
        matches = pair_boxes(full_frame_boxes(frame, 1920, 1080), annotation["boxes"])
        variants = {key: copy.deepcopy(frame) for key in stages}
        for variant in variants.values():
            for box in variant["boxes"]:
                box["identity"] = asdict(IdentityMatch())
        for owner, key in owners.items():
            row = evidence["query_crops"][key]
            top = row["ranked"][0]
            accepted = select(row["ranked"])
            unique = top["score"] > 0 and row["margin"] > 0
            variants["positive_unique_rank1"]["boxes"][owner]["identity"] = (
                asdict(
                    IdentityMatch(top["identity_id"], top["name"], float(top["score"]))
                )
                if unique
                else asdict(IdentityMatch())
            )
            variants["single_sample_inlier_rule"]["boxes"][owner]["identity"] = asdict(
                accepted
            )
            truth = (
                annotation["boxes"][matches[owner]]["cow"]
                if owner in matches
                else "unmatched"
            )
            records.append(
                {
                    "clip": annotation["clip"],
                    "frame": annotation["frame"],
                    "truth": truth,
                    "pixels_sha256": key,
                    "keypoints": row["keypoints"],
                    "margin": row["margin"],
                    "accepted": int(accepted.identity_id, 16)
                    if accepted.identity_id
                    else None,
                    "best": top,
                    "ranked": row["ranked"],
                }
            )
            counts = per_cow[str(truth)]
            counts["available_crops"] += 1
            counts["correct_unique_rank1"] += int(
                unique and int(top["identity_id"], 16) == truth
            )
            counts["positive_wrong_or_unknown_rank1"] += int(
                unique and int(top["identity_id"], 16) != truth
            )
            counts["tied_or_zero_evidence"] += int(not unique)
            counts["accepted"] += int(accepted.identity_id is not None)
        for stage, variant in variants.items():
            counts, _ = score_frame(variant, annotation, known)
            stages[stage].update(counts)
    gallery = Path(freeze["gallery"])
    catalog = IdentityCatalog(gallery)
    gallery_points = {
        cow.name: [
            len(extract(catalog.read_image(sample))[0]) for sample in cow.samples
        ]
        for cow in catalog.load().identities
    }
    query_points = [row["keypoints"] for row in evidence["query_crops"].values()]
    result = {
        "scope": "Post-result diagnostic, no policy or threshold changes. Truth enters only scoring. Unique positive top1 excludes arbitrary all-zero/tied winners. Single-sample labels omit temporal agreement and are not a deployable policy.",
        "protocol_sha256": digest(FREEZE),
        "evidence_sha256": digest(OUTPUT / "evidence.json"),
        "source_sha256": digest(Path(__file__)),
        "stages": {key: rates(value) for key, value in stages.items()},
        "per_cow": {key: dict(value) for key, value in per_cow.items()},
        "gallery_keypoints": gallery_points,
        "query_keypoints": {
            "count": len(query_points),
            "min": min(query_points),
            "median": float(np.median(query_points)),
            "max": max(query_points),
        },
        "records": records,
    }
    write_json(REPORT, result)
    montage(records, gallery, OUTPUT / "features" / evidence["fingerprint"])
    print(json.dumps({key: value for key, value in result.items() if key != "records"}))


if __name__ == "__main__":
    cv2.setNumThreads(2)
    main()
