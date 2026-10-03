"""Deterministic prediction-only contamination sample before dense training."""

import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from cutie_features import object_crops
from PIL import Image, ImageDraw, ImageOps
from recognition_masked_pilot import eligible
from video_assessment import pixels_hash

ROOT = Path(__file__).parent
RUN = Path(".cache/cow-cutie/crowded-joint-extended")
CLIP = Path(".cache/cow-cutie/reserved-2fps-clip")
OUTPUT = Path(".cache/cow-temporal-contamination-review")
SELECTION = ROOT / "results/2026-10-03/recognition/temporal-review-selection.json"


def quality_rows(timeline):
    rows, previous, run_ids = [], {}, {}
    for frame in timeline:
        if not 0 <= frame["second"] <= 629:
            continue
        stats = {item["track_id"]: item for item in frame["objects"]}
        for box in frame["boxes"]:
            track = box["track_id"]
            if not eligible(frame, box, stats):
                continue
            second = int(frame["second"])
            if previous.get(track) != second - 1:
                run_ids[track] = second
            previous[track] = second
            rows.append(
                {
                    "second": second,
                    "track_id": track,
                    "run_start": run_ids[track],
                    "box": [box[k] for k in ("x1", "y1", "x2", "y2")],
                    "source_pixels_sha256": frame["source_pixels_sha256"],
                    "mask_sha256": frame["mask_sha256"],
                }
            )
    return rows


def select(rows):
    selected = []
    for track in range(4):
        for bin_id in range(4):
            groups = {}
            for row in rows:
                if row["track_id"] == track and row["second"] // 105 == bin_id:
                    groups.setdefault(row["run_start"], []).append(row)
            if groups:
                run = min(groups.values(), key=lambda r: (-len(r), r[0]["second"]))
                selected.append({**run[(len(run) - 1) // 2], "bin": bin_id})
    return selected


def render(selected):
    OUTPUT.mkdir(parents=True, exist_ok=False)
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    clip = json.loads((CLIP / "sampled.json").read_text())
    by_second = {row["second"]: [] for row in selected}
    for row in selected:
        by_second[row["second"]].append(row)
    rendered = []
    try:
        for source in clip["rows"]:
            if source["second"] > max(by_second):
                break
            if not capture.grab():
                raise ValueError("Source clip truncated")
            if source["second"] not in by_second:
                continue
            ok, image = capture.retrieve()
            if not ok or pixels_hash(image) != source["pixels_sha256"]:
                raise ValueError("Source pixels changed")
            second = int(source["second"])
            mask_path = RUN / "masks" / f"{second}.png"
            if digest(mask_path) != by_second[second][0]["mask_sha256"]:
                raise ValueError("Teacher mask changed")
            boxes, crops, _ = object_crops(
                image, cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
            )
            crops = {b["track_id"]: c for b, c in zip(boxes, crops, strict=True)}
            for row in by_second[second]:
                stem = f"slot{row['track_id'] + 1}-bin{row['bin']}-s{second}"
                path = OUTPUT / f"{stem}.png"
                context = OUTPUT / f"{stem}-context.png"
                marked = image.copy()
                cv2.rectangle(
                    marked,
                    tuple(row["box"][:2]),
                    tuple(row["box"][2:]),
                    (0, 255, 255),
                    2,
                )
                if not cv2.imwrite(
                    str(path), crops[row["track_id"]]
                ) or not cv2.imwrite(str(context), marked):
                    raise OSError("Cannot save review pixels")
                rendered.append(
                    {
                        **row,
                        "crop": str(path),
                        "context": str(context),
                        "crop_sha256": digest(path),
                        "context_sha256": digest(context),
                    }
                )
    finally:
        capture.release()
    save_sheet(rendered)


def save_sheet(rendered):
    rendered.sort(key=lambda row: (row["track_id"], row["bin"]))
    sheet = Image.new("RGB", (1600, 1240), "white")
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(rendered):
        x, y = (i % 4) * 400, (i // 4) * 310
        draw.text(
            (x + 8, y + 5),
            f"Slot{row['track_id'] + 1} / {row['second']}s / run begins {row['run_start']}s",
            fill="black",
        )
        for key, bounds, offset in (
            ("context", (384, 180), (8, 26)),
            ("crop", (384, 96), (8, 210)),
        ):
            image = Image.open(row[key]).convert("RGB")
            image = ImageOps.contain(image, bounds)
            sheet.paste(image, (x + offset[0], y + offset[1]))
    sheet.save(OUTPUT / "contact-sheet.jpg", quality=95)
    write_json(
        OUTPUT / "manifest.json",
        {
            "selection_sha256": digest(SELECTION),
            "rows": rendered,
            "sheet_sha256": digest(OUTPUT / "contact-sheet.jpg"),
        },
    )


def main():
    if SELECTION.exists() or OUTPUT.exists():
        raise FileExistsError("Keep the original prediction-only selection")
    teacher = json.loads((RUN / "streaming.json").read_text())
    selected = select(quality_rows(teacher["timeline"]))
    write_json(
        SELECTION,
        {
            "method": "Slots1..4, four105-second bins0..419; midpoint of longest uninterrupted quality run within each bin, tie earliest. No truth or embedding selection. No later replacement after review.",
            "files": {
                str(p): digest(p)
                for p in (
                    Path(__file__),
                    ROOT / "recognition_masked_pilot.py",
                    ROOT / "cutie_features.py",
                    RUN / "streaming.json",
                    CLIP / "sampled.json",
                    CLIP / "sampled.avi",
                )
            },
            "rows": selected,
        },
    )
    render(selected)
    print(
        json.dumps(
            {
                "rows": len(selected),
                "selection": str(SELECTION),
                "sheet": str(OUTPUT / "contact-sheet.jpg"),
            }
        )
    )


if __name__ == "__main__":
    main()
