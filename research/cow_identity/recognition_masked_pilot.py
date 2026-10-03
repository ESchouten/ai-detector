"""Freeze twelve quality-selected reference questions before visual review.

Only cached prediction metadata at0..629 determines selection. Rendering uses
its original source pixels/masks; no model, biological query labels or embeddings.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from cutie_features import object_crops
from video_assessment import pixels_hash

ROOT = Path(__file__).parent
RUN = Path(".cache/cow-cutie/streaming-development")
CLIP = Path(".cache/cow-cutie/calibration-clip")
SEEDS = Path(".cache/cow-cutie/actual-seed-masks/manifest.json")


def eligible(frame, box, statistics):
    track = box["track_id"]
    x1, y1, x2, y2 = (box[key] for key in ("x1", "y1", "x2", "y2"))
    return (
        track in range(6)
        and track + 1 not in frame["conflicted_ids"]
        and track in {pair["track_id"] for pair in frame["reciprocal_pairs"]}
        and statistics[track]["p10_probability"] >= 0.7
        and x1 >= 1
        and y1 >= 1
        and x2 < 799
        and y2 < 599
        and min(x2 - x1, y2 - y1) >= 64
    )


def candidates(timeline):
    def rank(row):
        return -row["p10_probability"], -row["area"], row["second"]

    winners = {}
    frames = [row for row in timeline if 0 <= row["second"] <= 629]
    if [row["second"] for row in frames] != list(range(630)):
        raise ValueError("Preserve every integer timestamp0..629")
    for frame in frames:
        stats = {row["track_id"]: row for row in frame["objects"]}
        for box in frame["boxes"]:
            if not eligible(frame, box, stats):
                continue
            track, second = box["track_id"], frame["second"]
            item = {
                "track_id": track,
                "suggested_cow": track + 1,
                "second": second,
                "bin": second // 63,
                "box": [box[key] for key in ("x1", "y1", "x2", "y2")],
                "area": stats[track]["area"],
                "p10_probability": stats[track]["p10_probability"],
                "source_pixels_sha256": frame["source_pixels_sha256"],
                "mask_sha256": frame["mask_sha256"],
            }
            key = (track, item["bin"])
            if key not in winners or rank(item) < rank(winners[key]):
                winners[key] = item
    return [winners[key] for key in sorted(winners)]


def pilot(winners):
    selected = []
    for track in range(6):
        rows = [row for row in winners if row["track_id"] == track and row["bin"] >= 5]
        if rows:
            selected.append(rows[0])
            if len(rows) > 1:
                selected.append(rows[-1])
    return [{"candidate": index, **row} for index, row in enumerate(selected)]


def freeze(path):
    sources = [
        Path(__file__),
        ROOT / "test_recognition_masked_pilot.py",
        ROOT / "benchmark.py",
        ROOT / "cutie_features.py",
        ROOT / "detection_cutie.py",
        ROOT / "detection_streaming.py",
        ROOT / "detection_cutie_variants.py",
        ROOT / "video_assessment.py",
        RUN / "streaming.json",
        CLIP / "sampled.json",
        CLIP / "sampled.avi",
        SEEDS,
    ]
    write_json(
        path,
        {
            "status": "FROZEN_SELECTION_AND_RENDER_ONLY",
            "version": 2,
            "identity_indexing": "track_id is zero-based; recorded conflicted_ids are one-based stable mask IDs, so compare track_id+1.",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {str(p): digest(p) for p in sources},
            "inputs": {"run": str(RUN), "clip": str(CLIP), "seeds": str(SEEDS)},
            "source_seconds": [0, 629],
            "known_slots": list(range(6)),
            "bins": "Ten fixed63-second bins starting0; each ends inclusively62+63*i",
            "quality": "p10>=.7, no recorded quarantine, existing same-frame reciprocal confirmation, unclipped>=64px on both axes. No query label, embedding or outcome.",
            "ranking": "Within each slot/bin: highest raw-mask p10, then largest raw-mask area, then earliest second. One winner per bin.",
            "pilot": "For each named slot, choose first and last available winner among bins5..9. At most12 questions; if fewer than2 available, preserve fewer. No alternate/backfill after review rejection.",
            "crop": "Reuse object_crops: tight largest8-connected foreground, other pixels127, no alignment. Original whole context retained separately.",
            "review": "Suggestions are not truth. Independent biological confirmation against initial confirmed source/mask is required before enrollment; ambiguity rejects. No encoding or query scoring authorized by this protocol.",
            "limits": "Actual-proposal-seeded development run; early-scene localizer training optimism. No source later than629 decoded. Not an autonomous re-entry test.",
            "libraries": {"opencv": cv2.__version__, "numpy": np.__version__},
        },
    )


def checked(protocol_path):
    protocol = json.loads(protocol_path.read_text())
    if any(digest(Path(p)) != h for p, h in protocol["files"].items()):
        raise ValueError("Frozen pilot input changed")
    return protocol


def select(protocol_path, output):
    protocol = checked(protocol_path)
    run = json.loads((Path(protocol["inputs"]["run"]) / "streaming.json").read_text())
    if not run["complete"]:
        raise ValueError("Use completed actual-proposal-seeded propagation")
    winners = candidates(run["timeline"])
    write_json(
        output,
        {
            "protocol_sha256": digest(protocol_path),
            "status": "PENDING_INDEPENDENT_REVIEW",
            "winners": winners,
            "pilot": pilot(winners),
            "labels": "suggested_cow is original slot bookkeeping, never an accepted biological label",
        },
    )


def save_pixels(path, image):
    if not cv2.imwrite(str(path), image):
        raise OSError(f"Cannot save {path}")
    return {
        "path": str(path),
        "sha256": digest(path),
        "pixels_sha256": pixels_hash(image),
    }


def render_frame(image, second, selected, run, output):
    frame = next(row for row in run["timeline"] if row["second"] == second)
    if pixels_hash(image) != frame["source_pixels_sha256"]:
        raise ValueError("Decoded pixels differ from original runtime")
    path = RUN / "masks" / f"{second}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Original predicted mask changed")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    boxes, crops, _ = object_crops(image, mask)
    by_track = {
        box["track_id"]: (box, crop) for box, crop in zip(boxes, crops, strict=True)
    }
    rows = []
    for item in selected:
        if item["second"] != second:
            continue
        box, crop = by_track[item["track_id"]]
        if [box[k] for k in ("x1", "y1", "x2", "y2")] != item["box"]:
            raise ValueError("Rendered LCC geometry differs from selected proposal")
        stem = (
            f"candidate-{item['candidate']:02d}"
            if "candidate" in item
            else f"initial-{item['track_id'] + 1}"
        )
        context = image.copy()
        cv2.rectangle(
            context, tuple(item["box"][:2]), tuple(item["box"][2:]), (0, 220, 255), 2
        )
        rows.append(
            {
                **item,
                "foreground": save_pixels(output / f"{stem}.png", crop),
                "context": save_pixels(output / f"{stem}-context.png", image),
                "marked_context": save_pixels(
                    output / f"{stem}-marked-context.png", context
                ),
            }
        )
    return rows


def render(protocol_path, selection_path, output):
    protocol = checked(protocol_path)
    selection = json.loads(selection_path.read_text())
    if selection["protocol_sha256"] != digest(protocol_path):
        raise ValueError("Selection must be saved before any review pixels")
    run = json.loads((RUN / "streaming.json").read_text())
    first = run["timeline"][0]
    initial = [
        {
            "track_id": b["track_id"],
            "suggested_cow": b["track_id"] + 1,
            "second": 0,
            "box": [b[k] for k in ("x1", "y1", "x2", "y2")],
        }
        for b in first["boxes"]
        if b["track_id"] < 6
    ]
    chosen = selection["pilot"] + initial
    seconds = {row["second"] for row in chosen}
    clip = json.loads((CLIP / "sampled.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    rows = []
    try:
        for source in clip["rows"]:
            second = source["second"]
            if second > max(seconds):
                break
            if not capture.grab():
                raise ValueError("Source clip ended prematurely")
            if second in seconds:
                ok, image = capture.retrieve()
                if not ok:
                    raise ValueError("Source frame could not decode")
                rows.extend(render_frame(image, int(second), chosen, run, output))
    finally:
        capture.release()
    if len(rows) != len(chosen):
        raise ValueError("Every selected photo and initial comparison must render")
    write_json(
        output / "manifest.json",
        {
            "protocol_sha256": digest(protocol_path),
            "selection_sha256": digest(selection_path),
            "status": "READY_FOR_INDEPENDENT_REVIEW_NOT_ENROLLED",
            "rows": rows,
            "seed_manifest_sha256": protocol["files"][str(SEEDS)],
            "initial_comparison": "Frame-zero source and recorded seed-derived foreground; original accepted proposal and SAM-mask provenance bound by the seed manifest.",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "select", "render"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error(
            "Use a fresh output; previous freezes and selections are immutable"
        )
    if args.mode == "freeze":
        freeze(args.protocol)
    elif args.mode == "select":
        select(args.protocol, args.output)
    else:
        render(args.protocol, args.selection, args.output)
