"""Inspect verified local whole frames without models, OCR or new downloads.

Scene groups are a proposed development split, not verified capture sessions or
independent animals. Missing annotation files never become negative examples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = (
    ROOT
    / "research/cow_identity/results/2026-10-03/ear-tags/ownership-subset-inventory.json"
)
OUTDOOR = {1207, 2156, 2242, 2328, 2415, 2501, 2587, 2674}
LOW_RESOLUTION = {1897, 1983, 2070}
INVENTORY_SHA256 = "9aab8579ef83cbe5e241d803f8a76d48935ab9f55dd89faf8e2df3516bbecf71"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proposed_group(identifier: str) -> tuple[str, str]:
    number = int(identifier.removeprefix("cow"))
    if number in OUTDOOR:
        return "outdoor_pen", "evaluation"
    if number in LOW_RESOLUTION:
        return "undated_low_resolution_camera", "development"
    return "indoor_feeding_and_pen", "training"


def image_facts(row: dict) -> dict:
    path = ROOT / row["image"]
    if digest(path) != row["image_sha256"]:
        raise ValueError(f"Source image changed: {row['id']}")
    label = path.with_suffix(".txt")
    if label.exists() != row["label_available"]:
        raise ValueError(f"Annotation availability changed: {row['id']}")
    with Image.open(path) as image:
        if list(image.size) != row["shape"]:
            raise ValueError("Inventory shape is explicitly width,height")
        if label.exists():
            boxes = []
            for line in label.read_text().splitlines():
                cls, x, y, width, height = map(float, line.split())
                if cls != 0:
                    raise ValueError("Only published tag class0 is expected")
                boxes.append(
                    [
                        (x - width / 2) * image.width,
                        (y - height / 2) * image.height,
                        (x + width / 2) * image.width,
                        (y + height / 2) * image.height,
                    ]
                )
            if len(boxes) != len(row["tags"]) or not np.allclose(
                boxes, [tag["xyxy"] for tag in row["tags"]], rtol=0, atol=1e-6
            ):
                raise ValueError("Published tag geometry differs from frozen inventory")
        rgb = np.asarray(image.convert("RGB"))
        pixel_hash = hashlib.sha256(str((rgb.shape, rgb.dtype)).encode())
        pixel_hash.update(rgb.tobytes())
        exif = image.getexif()
        metadata = {
            name: str(exif[key])
            for key, name in (
                (271, "make"),
                (272, "model"),
                (306, "date_time"),
                (274, "orientation"),
            )
            if key in exif
        }
        group, split = proposed_group(row["id"])
        return {
            "id": row["id"],
            "image": row["image"],
            "image_sha256": row["image_sha256"],
            "rgb_pixels_sha256": pixel_hash.hexdigest(),
            "width": image.width,
            "height": image.height,
            "exif": metadata,
            "date_reliability": "factory-like date; not a usable capture date"
            if metadata.get("date_time", "").startswith("2008:01:01")
            else "publisher file metadata; not independently verified"
            if "date_time" in metadata
            else "absent",
            "scene_group": group,
            "proposed_split": split if label.exists() else "unannotated",
            "annotation_available": label.exists(),
            "label_sha256": digest(label) if label.exists() else None,
            "tag_rectangles": len(row["tags"]),
            "ownership_annotations": "absent",
        }


def inventory() -> dict:
    if digest(INVENTORY) != INVENTORY_SHA256:
        raise ValueError("Original whole-frame inventory changed")
    source = json.loads(INVENTORY.read_text())
    rows = [image_facts(row) for row in source["rows"]]
    pixels: dict[str, set[str]] = {}
    for row in rows:
        pixels.setdefault(row["rgb_pixels_sha256"], set()).add(row["proposed_split"])
    if any(len(splits) > 1 for splits in pixels.values()):
        raise ValueError("Exact duplicate decoded image crosses proposed splits")
    counts = {}
    for split in ("training", "development", "evaluation", "unannotated"):
        selected = [row for row in rows if row["proposed_split"] == split]
        counts[split] = {
            "images": len(selected),
            "tag_rectangles": sum(row["tag_rectangles"] for row in selected),
        }
    return {
        "status": "PREPARATION_ONLY_NO_MODELS_OR_TRAINING",
        "source_inventory_sha256": digest(INVENTORY),
        "recipe_sha256": digest(Path(__file__)),
        "grouping": "AI visual scene grouping of all32 already-exposed clean frames. Keep all outdoor views together, including March1 cow1207. Keep three low-resolution frames together. Other indoor frames form one training scene group. Requires independent grouping review before training.",
        "limitations": [
            "Dates and biological identities are not source-certified; no farm, animal or full-session independence claim.",
            "March1 includes indoor and outdoor images; the proposed scene split is not date-disjoint.",
            "Low-resolution camera may depict the same indoor location/animals; development measurements are not independent validation.",
            "Exact pixel duplicates are checked; lack of duplicate pixels does not exclude related video frames.",
            "Three missing-label images remain unannotated, never negative training examples.",
            "Published rectangles locate tags, not which head/body owns them or what digits they contain.",
        ],
        "counts": counts,
        "exif_dates": dict(
            Counter(row["exif"].get("date_time", "absent")[:10] for row in rows)
        ),
        "exact_pixel_duplicate_groups": sum(
            count > 1
            for count in Counter(row["rgb_pixels_sha256"] for row in rows).values()
        ),
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["counts"]))
