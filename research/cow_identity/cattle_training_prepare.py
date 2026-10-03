"""Prepare bounded, dated public-cattle crops from local archives; never train.

Publisher Cows2021 Test is explicitly repurposed as supervised training data.
Its anonymous Train tracklets are excluded. OpenCows2020 is inventoried but not
mixed in because physical-animal overlap with Bristol data is unresolved.
"""

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from benchmark import digest, write_json
from PIL import Image

SEED = "public-cattle-v1"
COHORT = {
    "cows2021": {
        "source": "https://doi.org/10.5523/bris.4vnrca7qw1642qlwxjadp87h7",
        "license": "Non-Commercial Government Licence",
        "publisher_split": "Identification/Test, deliberately repurposed; never a Cows2021 benchmark claim",
    },
    "sideview2026": {
        "source": "https://doi.org/10.5281/zenodo.21605650",
        "license": "CC-BY-4.0, as stated in publisher README",
        "publisher_split": "parlor; no official train/test split",
    },
}


def stable_order(value):
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def cows2021_inventory(archive):
    rows = []
    with ZipFile(archive) as source:
        names = source.namelist()
        for name in names:
            if "/Identification/Test/" not in name or not name.endswith(".jpg"):
                continue
            identity = f"cows2021:{name.split('/')[-2]}"
            day = re.search(r"\d{4}-\d{2}-\d{2}", name)[0]
            rows.append(
                {
                    "dataset": "cows2021",
                    "identity": identity,
                    "day": day,
                    "group": f"{identity}:{day}",
                    "member": name,
                    "archive": str(archive),
                    "view": "orientation-rectified top-down torso",
                }
            )
        tracklets = [
            name
            for name in names
            if "/Identification/Train/" in name and name.endswith(".jpg")
        ]
    return rows, {
        "identity_images": len(rows),
        "anonymous_tracklet_images_excluded": len(tracklets),
    }


def sideview_inventory(root):
    rows = []
    subset_counts = Counter()
    with (root / "manifest.csv").open(newline="") as stream:
        for item in csv.DictReader(stream):
            subset_counts[item["subset"]] += 1
            path = root / item["image_path"]
            if item["subset"] != "parlor" or not path.is_file():
                continue
            identity = f"sideview2026:{item['individual_id']}"
            day = int(float(item["time_offset_s"]) // 86400)
            rows.append(
                {
                    "dataset": "sideview2026",
                    "identity": identity,
                    "day": f"offset-day-{day:06d}",
                    "group": f"{identity}:offset-day-{day:06d}",
                    "source_path": str(path),
                    "source_sha256": item["sha256"],
                    "mask_path": str(root / item["mask_path"]),
                    "mask_member": item["mask_path"],
                    "time_offset_s": float(item["time_offset_s"]),
                    "view": "right side, parlor, tight mask bounding-box crop",
                }
            )
    return rows, {
        "local_identity_images": len(rows),
        "publisher_subset_images": dict(subset_counts),
    }


def select_cohort(rows):
    """One image per cow/day; 20% held-out identities, never random frame splits."""
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[row["identity"]][row["day"]].append(row)
    eligible = {identity: days for identity, days in groups.items() if len(days) >= 5}
    by_dataset = defaultdict(list)
    for identity in eligible:
        by_dataset[identity.split(":")[0]].append(identity)
    validation_ids = set()
    unknown_ids = set()
    for identities in by_dataset.values():
        ordered = sorted(identities, key=stable_order)
        validation = ordered[: max(1, len(ordered) // 5)]
        validation_ids.update(validation)
        unknown_ids.update(validation[: max(1, len(validation) // 5)])
    selected = []
    for identity, days in sorted(eligible.items()):
        ordered_days = sorted(days)
        count = min(16, len(ordered_days))
        indices = np.linspace(0, len(ordered_days) - 1, count).astype(int)
        chosen_days = [ordered_days[i] for i in indices]
        for index, day in enumerate(chosen_days):
            row = min(
                days[day],
                key=lambda row: stable_order(row.get("member", row.get("source_path"))),
            )
            split = "train"
            if identity in validation_ids:
                split = "validation_query"
                if identity not in unknown_ids and index < (len(chosen_days) + 1) // 2:
                    split = "validation_gallery"
            selected.append(
                {**row, "split": split, "validation_unknown": identity in unknown_ids}
            )
    return selected, {
        "excluded_insufficient_days": sorted(set(groups) - set(eligible)),
        "training_identities": sorted(set(eligible) - validation_ids),
        "validation_identities": sorted(validation_ids),
        "validation_unknown_identities": sorted(unknown_ids),
    }


def crop_image(row, cows_archive, mask_hashes, output):
    if row["dataset"] == "cows2021":
        raw = cows_archive.read(row["member"])
        source_sha256 = hashlib.sha256(raw).hexdigest()
        if row.get("source_sha256", source_sha256) != source_sha256:
            raise ValueError(f"Selected archive image changed: {row['member']}")
        row = {**row, "source_sha256": source_sha256}
        with Image.open(io.BytesIO(raw)) as image:
            pixels = np.asarray(image.convert("RGB"))
        extension = ".jpg"
    else:
        source, mask_path = Path(row["source_path"]), Path(row["mask_path"])
        if digest(source) != row["source_sha256"]:
            raise ValueError(f"Publisher image checksum differs: {source}")
        mask_sha256 = digest(mask_path)
        if mask_sha256 != mask_hashes[row["mask_member"]]:
            raise ValueError(f"Publisher mask checksum differs: {mask_path}")
        with Image.open(mask_path) as image:
            mask = np.asarray(image.convert("L")) > 0
        y, x = np.nonzero(mask)
        bounds = [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1]
        with Image.open(source) as image:
            pixels = np.asarray(image.convert("RGB").crop(bounds))
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        raw = stream.getvalue()
        row = {**row, "mask_sha256": mask_sha256, "crop_xyxy": bounds}
        extension = ".png"
    checksum = hashlib.sha256(raw).hexdigest()
    dataset, identity = row["identity"].split(":")
    path = output / "images" / dataset / identity / f"{checksum[:20]}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(raw)
    if digest(path) != checksum:
        raise ValueError(f"Existing extracted image changed: {path}")
    return {
        **row,
        "path": str(path),
        "sha256": checksum,
        "pixels_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "width": pixels.shape[1],
        "height": pixels.shape[0],
    }


def validate_manifest(rows):
    identities = defaultdict(set)
    pixels = defaultdict(set)
    groups = defaultdict(set)
    for row in rows:
        role = "train" if row["split"] == "train" else "validation"
        identities[row["identity"]].add(role)
        pixels[row["pixels_sha256"]].add(row["identity"])
        groups[row["group"]].add(row["split"])
    if any(len(roles) > 1 for roles in identities.values()):
        raise ValueError("An identity appears in training and validation")
    if any(len(splits) > 1 for splits in groups.values()):
        raise ValueError("A capture-day group straddles split boundaries")
    if any(len(owners) > 1 for owners in pixels.values()):
        raise ValueError("Identical pixels have conflicting identity labels")
    if len(pixels) != len(rows):
        raise ValueError("Duplicate pixel content remains in selected data")


def prepare(args):
    cows_archive = args.datasets / "Cows2021/Cows2021.zip"
    sideview = args.datasets / "SideViewCows2026"
    cows, cows_info = cows2021_inventory(cows_archive)
    side, side_info = sideview_inventory(sideview)
    selected, selection = select_cohort(cows + side)
    if args.selection is not None:
        selected = [
            json.loads(line) for line in args.selection.read_text().splitlines()
        ]
        for row in selected:
            for key in ("archive", "source_path", "mask_path"):
                if key in row:
                    row[key] = str(
                        args.datasets / Path(row[key]).relative_to("datasets")
                    )
        selection.update(
            training_identities=sorted(
                {row["identity"] for row in selected if row["split"] == "train"}
            ),
            validation_identities=sorted(
                {row["identity"] for row in selected if row["split"] != "train"}
            ),
            validation_unknown_identities=sorted(
                {row["identity"] for row in selected if row["validation_unknown"]}
            ),
        )
    mask_hashes = {}
    for line in (sideview / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split(maxsplit=1)
        mask_hashes[name.removeprefix("*").removeprefix("./")] = checksum
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with ZipFile(cows_archive) as archive:
        for index, row in enumerate(selected):
            rows.append(crop_image(row, archive, mask_hashes, args.output))
            if index % 500 == 0:
                print(
                    json.dumps({"extracted": index, "selected": len(selected)}),
                    flush=True,
                )
    validate_manifest(rows)
    with ZipFile(args.datasets / "OpenCows2020/OpenCows2020.zip") as archive:
        excluded_open_cows = Counter(
            name.split("/images/")[1].split("/")[0]
            for name in archive.namelist()
            if "/identification/images/" in name and name.endswith(".jpg")
        )
    manifest = {
        "contract": {
            "version": 1,
            "purpose": "Prepared public-cattle metric learning experiment; no training performed",
            "seed": SEED,
            "sources": COHORT,
            "cows2021_archive_sha256": digest(cows_archive),
            "sideview_manifest_sha256": digest(sideview / "manifest.csv"),
            "sideview_hashes_sha256": digest(sideview / "SHA256SUMS"),
            "selection": "At least 5 observed days; at most 16 evenly spaced days/cow, one stable-hash-selected image/day; per-dataset 20% identity-disjoint validation, 20% of validation identities unenrolled",
            "evaluation_excluded": [
                "8-calves (all frames and identities)",
                "ETHZ (all crops, videos and identities)",
            ],
            "pretraining_overlap": "MIEWid foundation-training membership is not fully audited; no claim of foundation-unseen cows",
        },
        "inventory": {
            "cows2021": cows_info,
            "sideview2026": side_info,
            "opencows2020_excluded": dict(excluded_open_cows),
        },
        "selection": selection,
        "rows": rows,
    }
    write_json(args.output / "manifest.json", manifest)
    summary = {
        "contract": manifest["contract"],
        "inventory": manifest["inventory"],
        "manifest_sha256": digest(args.output / "manifest.json"),
        "images": len(rows),
        "identities": len({row["identity"] for row in rows}),
        "by_split": dict(Counter(row["split"] for row in rows)),
        "by_dataset": dict(Counter(row["dataset"] for row in rows)),
        "training_identities": len(selection["training_identities"]),
        "validation_identities": len(selection["validation_identities"]),
        "unknown_validation_identities": len(
            selection["validation_unknown_identities"]
        ),
        "excluded_insufficient_days": selection["excluded_insufficient_days"],
    }
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, default=Path("datasets"))
    parser.add_argument(
        "--selection",
        type=Path,
        help="Replay a frozen source selection JSONL instead of inventory-based selection",
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/cattle-public-training")
    )
    prepare(parser.parse_args())
