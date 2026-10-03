"""Inventory public ear-tag crops and freeze grouped OCR splits before inference."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from benchmark import digest, write_json

ROOT = Path(__file__).parent
ARCHIVE = Path("datasets/cow-eartag-recognition/cow-eartag-recognition-v1.zip")
EXPECTED = "4f0aa55d97cae2052933bf614f62200f89aeadb02563f7ccd49bff7e139cb65a"
PREFIX = "Cow eartag recognition dataset/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def perceptual_hashes(image):
    small = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    spectrum = cv2.dct(small)[:8, :8].reshape(-1)
    phash = spectrum > np.median(spectrum[1:])
    horizontal = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
    dhash = horizontal[:, 1:] > horizontal[:, :-1]
    return [int.from_bytes(np.packbits(values).tobytes()) for values in (phash, dhash)]


def annotation(raw):
    lines = []
    for line in raw.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        values = line.split(",", 8)
        if len(values) != 9:
            raise ValueError("Expected eight polygon coordinates plus literal text")
        points = [float(number) for number in values[:8]]
        if not all(np.isfinite(points)):
            raise ValueError("Nonfinite polygon")
        lines.append({"polygon": points, "text": values[8].strip()})
    return lines


def inventory(destination):
    if digest(ARCHIVE) != EXPECTED:
        raise ValueError("Public version1 archive changed")
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    with ZipFile(ARCHIVE) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".jpg"):
                continue
            stem = Path(name).stem
            if not re.fullmatch(r"eartags\d+", stem):
                raise ValueError("Unexpected source image path")
            label = PREFIX + "Labels/gt_" + stem + ".txt"
            content, text = archive.read(name), archive.read(label)
            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError(f"Unreadable source crop: {name}")
            lines = annotation(text)
            path = destination / (stem + ".jpg")
            path.write_bytes(content)
            numeric = sorted(
                {
                    row["text"]
                    for row in lines
                    if re.fullmatch(r"[0-9]{4,}", row["text"])
                }
            )
            rows.append(
                {
                    "id": stem,
                    "archive_image": name,
                    "archive_label": label,
                    "image": str(path),
                    "image_sha256": sha(content),
                    "label_sha256": sha(text),
                    "pixels_sha256": sha(str(image.shape).encode() + image.tobytes()),
                    "height": image.shape[0],
                    "width": image.shape[1],
                    "lines": lines,
                    "numeric_id_candidates": numeric,
                    "phash_dhash": perceptual_hashes(image),
                }
            )
    return rows


def grouped(rows):
    parents = list(range(len(rows)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def union(i, j):
        left, right = root(i), root(j)
        parents[max(left, right)] = min(left, right)

    seen = {}
    for i, row in enumerate(rows):
        # Leading-zero aliases block split leakage only; transcription stays literal.
        keys = [
            ("number", value.lstrip("0") or "0")
            for value in row["numeric_id_candidates"]
        ]
        keys.append(("pixels", row["pixels_sha256"]))
        for key in keys:
            union(i, seen.setdefault(key, i))
    near_pairs = []
    for i, left in enumerate(rows):
        p, d = left["phash_dhash"]
        for j in range(i):
            q, e = rows[j]["phash_dhash"]
            if (p ^ q).bit_count() <= 4 and (d ^ e).bit_count() <= 4:
                union(i, j)
                near_pairs.append([left["id"], rows[j]["id"]])
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row)
    assign_splits(groups)
    return near_pairs


def assign_splits(groups):
    for members in groups.values():
        group = sha(
            ("cegd-r-v1:" + "|".join(sorted(r["id"] for r in members))).encode()
        )
        bucket = int(group[:8], 16) % 10
        split = (
            "development" if bucket < 6 else "calibration" if bucket < 8 else "reserved"
        )
        if any(not r["numeric_id_candidates"] or not r["lines"] for r in members):
            split = "ambiguous_id"
        for row in members:
            row.update(group=group, split=split)


def sample(rows, split, limit):
    selected, seen = [], set()
    for row in sorted(
        rows,
        key=lambda r: (sha(("ocr-pilot-v1:" + r["image_sha256"]).encode()), r["id"]),
    ):
        if row["split"] == split and row["group"] not in seen and row["lines"]:
            selected.append(row["id"])
            seen.add(row["group"])
            if len(selected) == limit:
                break
    return selected


def prepare(args):
    rows = inventory(args.images)
    near_pairs = grouped(rows)
    manifest = {
        "archive": str(ARCHIVE),
        "archive_sha256": EXPECTED,
        "rows": rows,
        "near_duplicate_pairs": near_pairs,
    }
    write_json(args.manifest, manifest)
    counts = Counter(row["split"] for row in rows)
    protocol = {
        "scope": "Public preselected grayscale ear-tag crops; full literal transcription only. No tag localization, country/biological-ID schema, whole-animal association or live-camera success claim.",
        "source": "https://www.kaggle.com/datasets/fandaoerji/cow-eartag-recognition-dataset",
        "version": 1,
        "archive_sha256": EXPECTED,
        "files": {str(p): digest(p) for p in (Path(__file__), args.manifest, ARCHIVE)},
        "grouping": "Union all shared annotated ASCII numeric strings>=4chars (leading-zero aliases union for split only), exact decoded pixels, and pairs with BOTH64bitDCTpHash and64bitdHash Hamming<=4. Transitive groups stay together. No filename adjacency assumed to establish source video.",
        "splitting": "SHA256('cegd-r-v1:'+sortedmemberIDsjoinedby|), first8hex mod10:0–5development,6–7calibration,8–9reserved. Any group with missing/short-only ID annotations is ambiguous_id and excluded from identity-independent holdout.",
        "sampling": "SHA256('ocr-pilot-v1:'+sourceJPEGsha), source ID lexical tie; one nonempty-annotation image per group. Fixed64development pilot plus8ambiguous diagnostic examples. Fixed64calibration and100reserved for later evaluation, not opened or scored by this preparation.",
        "literal_text": "Preserve zeros, punctuation and all lines; do not concatenate lines into an animal ID or select the longest OCR result as truth. No roster supplied. Polygon line order retained as annotated; unordered full-tag transcription can be evaluated separately from reading order.",
        "pilot": sample(rows, "development", 64),
        "ambiguous_pilot": sample(rows, "ambiguous_id", 8),
        "calibration": sample(rows, "calibration", 64),
        "reserved": sample(rows, "reserved", 100),
        "inventory": {
            "images": len(rows),
            "split_images": dict(counts),
            "split_groups": {
                s: len({r["group"] for r in rows if r["split"] == s}) for s in counts
            },
            "line_counts": dict(Counter(len(r["lines"]) for r in rows)),
            "near_duplicate_pairs": len(near_pairs),
        },
        "limitations": [
            "Public archive contains3204images/labels, not advertised3238; preserve source as downloaded.",
            "Numeric ID candidates are annotation-derived blocking keys, not certified biological identities. Partial IDs, annotation typos and unprovided source-video membership can evade these safeguards.",
            "Dataset already filtered/preprocessed from detected tags; OCR capacity cannot be transferred to tiny blurred surveillance ear pixels.",
            "Printed/handwritten and country styles are not separately annotated; no style-specific accuracy inferred from text shape.",
        ],
    }
    write_json(args.protocol, protocol)
    print(json.dumps(protocol["inventory"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("images", "manifest", "protocol"):
        parser.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args()
    if any(path.exists() for path in (args.images, args.manifest, args.protocol)):
        parser.error("Preserve existing prepared datasets and frozen manifests")
    prepare(args)
