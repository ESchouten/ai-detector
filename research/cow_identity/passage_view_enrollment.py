"""Freeze first-day chronological view candidates without any query information."""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_crop_audit import tile
from passage_runtime import MANIFEST
from PIL import Image, ImageDraw, ImageOps

from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.domain.models import BoundingBox

SOURCE = Path(".cache/cow-passage-torso-enrollment")
OUTPUT = Path(".cache/cow-passage-view-enrollment")
PROTOCOL = Path(__file__).with_name("passage_view_enrollment_protocol.json")


def context_panel(image, candidate, source_row, second):
    canvas = Image.new("RGB", (780, 280), "white")
    pixels = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    canvas.paste(ImageOps.pad(pixels, (770, 215), color="#dddddd"), (5, 5))
    draw = ImageDraw.Draw(canvas)
    draw.text((5, 225), f"candidate{candidate} / source row{source_row}", fill="black")
    draw.text((5, 245), f"second{second}; native source context", fill="black")
    return canvas


def chronological_indices(indices, maximum=10):
    if len(indices) <= maximum:
        return indices
    return [
        indices[int(index)]
        for index in np.rint(np.linspace(0, len(indices) - 1, maximum))
    ]


def collect_candidates(proposals, manifest):
    known = {clip["clip"] for clip in manifest["clips"] if clip["role"] == "enrollment"}
    groups = {}
    for frame in proposals["frames"]:
        if frame["clip"] not in known:
            raise ValueError(
                "Only frozen first-day enrollment clips may supply candidates"
            )
        rows = [proposals["rows"][index] for index in frame["rows"]]
        shifted = tuple(
            replace(
                BoundingBox(**row["box"]),
                x1=row["box"]["x1"] + 2,
                x2=row["box"]["x2"] + 2,
                y1=row["box"]["y1"] + 2,
                y2=row["box"]["y2"] + 2,
            )
            for row in rows
        )
        for index, box, row in zip(frame["rows"], shifted, rows, strict=True):
            if usable_crop(
                box, shifted, row["frame_width"] + 4, row["frame_height"] + 4, 64, 0.2
            ):
                groups.setdefault(frame["clip"], []).append(index)
    return {
        clip: chronological_indices(
            sorted(indices, key=lambda i: (proposals["rows"][i]["local_frame"], i))
        )
        for clip, indices in groups.items()
    }


def prepare():
    if OUTPUT.exists() or PROTOCOL.exists():
        raise ValueError("Preserve frozen candidate selection")
    proposals = json.loads((SOURCE / "proposals.json").read_text())
    manifest = json.loads(MANIFEST.read_text())
    groups = collect_candidates(proposals, manifest)
    frames = {(row["clip"], row["local_frame"]): row for row in proposals["frames"]}
    OUTPUT.mkdir(parents=True)
    candidates, bound = [], {}
    for clip, indices in groups.items():
        sheet = Image.new("RGB", (1040, 280 * len(indices)), "white")
        for order, index in enumerate(indices):
            row = proposals["rows"][index]
            frame = frames[(clip, row["local_frame"])]
            crop_path, context_path = SOURCE / row["path"], SOURCE / frame["path"]
            crop, context = cv2.imread(str(crop_path)), cv2.imread(str(context_path))
            x1, y1, x2, y2 = (row["box"][key] for key in ("x1", "y1", "x2", "y2"))
            if not np.array_equal(crop, context[y1:y2, x1:x2]):
                raise ValueError("Crop pixels differ from their first-day frame")
            candidate = {
                "candidate": len(candidates),
                "source_row": index,
                "clip": clip,
                "second": row["second"],
                "frame": row["local_frame"],
                "crop": str(crop_path),
                "context": str(context_path),
                "crop_sha256": digest(crop_path),
                "context_sha256": digest(context_path),
                "box": row["box"],
                "original_boundary_eligible": row["eligible"],
            }
            candidates.append(candidate)
            bound[str(crop_path)], bound[str(context_path)] = (
                candidate["crop_sha256"],
                candidate["context_sha256"],
            )
            annotated = context.copy()
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 255), 3)
            context_tile = context_panel(
                annotated, candidate["candidate"], index, row["second"]
            )
            crop_tile = tile(
                crop,
                [
                    f"candidate{candidate['candidate']}",
                    "Review identity, visible coat and blur",
                ],
            )
            sheet.paste(context_tile, (0, 280 * order))
            sheet.paste(crop_tile, (780, 280 * order))
        sheet.save(OUTPUT / f"{clip}-review.jpg")
    candidate_path = OUTPUT / "candidates.json"
    write_json(
        candidate_path,
        {
            "source_proposals_sha256": digest(SOURCE / "proposals.json"),
            "manifest_sha256": digest(MANIFEST),
            "candidates": candidates,
            "selection_by_clip": groups,
        },
    )
    bound[str(candidate_path)] = digest(candidate_path)
    bound[str(SOURCE / "proposals.json")] = digest(SOURCE / "proposals.json")
    bound[str(MANIFEST)] = digest(MANIFEST)
    bound[str(Path(__file__))] = digest(Path(__file__))
    write_json(
        PROTOCOL,
        {
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "status": "First-day candidate selection frozen before independent review and query evaluation",
            "selection": "Existing June8 known-clip torso proposals only; preserve min64px and <=.2 overlap, allow boundary contact. Sort by native frame/source row, then take up to10 rounded equally-spaced chronological indices including first and last. No embeddings, June9 scores, query pixels or biological labels enter selection.",
            "review": "Independently confirm principal animal against original first-day source context and coat, reject blur/mixed identity/insufficient coat. Record a decision for every fixed candidate. Do not backfill rejected candidates or use query evidence. Keep all7intended-known, including2238 if none accepted.",
            "source_manifest": str(MANIFEST),
            "candidates": str(candidate_path),
            "candidate_count": len(candidates),
            "files": bound,
            "next_control": "Use the same frozen model/.65/.1/three-sample policy on exposed June9 only after selected references and implementation are frozen. No new training/threshold search; reserved crowded-calf windows remain unopened.",
            "effort": "At most10 proposed review images per principal passage; explicitly count accepted/rejected photos and separate this research collection from default app retention cadence.",
        },
    )
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "protocol_sha256": digest(PROTOCOL),
                "groups": groups,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    prepare()
