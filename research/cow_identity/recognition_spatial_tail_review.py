"""Extend the fixed prediction-only contamination review to newly trained slots5/6."""

import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from PIL import Image, ImageDraw, ImageOps
from recognition_temporal_features import checked, frame_crops, source_frames
from recognition_temporal_review import ROOT, RUN, quality_rows

PROTOCOL = ROOT / "recognition_temporal_pilot_v2_protocol.json"
OUTPUT = Path(".cache/cow-spatial-tail-review")
SELECTION = ROOT / "results/2026-10-03/recognition/spatial-tail-review-selection.json"


def select(rows):
    selected = []
    for track in (4, 5):
        for bin_id in range(4):
            runs = {}
            for row in rows:
                if row["track_id"] == track and row["second"] // 105 == bin_id:
                    runs.setdefault(row["run_start"], []).append(row)
            if runs:
                run = min(runs.values(), key=lambda r: (-len(r), r[0]["second"]))
                selected.append({**run[(len(run) - 1) // 2], "bin": bin_id})
    return selected


def render(protocol, selected, timeline):
    output = []
    for second, image in source_frames(protocol):
        if second > max(r["second"] for r in selected):
            break
        targets = [r for r in selected if r["second"] == second]
        if not targets:
            continue
        boxes, crops = frame_crops(timeline[second], image, RUN)
        indexed = {b["track_id"]: crop for b, crop in zip(boxes, crops, strict=True)}
        for row in targets:
            stem = f"slot{row['track_id'] + 1}-bin{row['bin']}-s{second}"
            crop = OUTPUT / f"{stem}.png"
            context = OUTPUT / f"{stem}-context.png"
            marked = image.copy()
            cv2.rectangle(
                marked, tuple(row["box"][:2]), tuple(row["box"][2:]), (0, 255, 255), 2
            )
            if not cv2.imwrite(str(crop), indexed[row["track_id"]]) or not cv2.imwrite(
                str(context), marked
            ):
                raise OSError("Cannot save reviewedpixels")
            output.append(
                {
                    **row,
                    "crop": str(crop),
                    "context": str(context),
                    "crop_sha256": digest(crop),
                    "context_sha256": digest(context),
                }
            )
    return sorted(output, key=lambda r: (r["track_id"], r["bin"]))


def main():
    if OUTPUT.exists() or SELECTION.exists():
        raise FileExistsError("Preserve frozenreview")
    protocol = checked(PROTOCOL)
    teacher = json.loads((RUN / "streaming.json").read_text())
    selected = select(quality_rows(teacher["timeline"]))
    write_json(
        SELECTION,
        {
            "method": "Exactpreceding4×105sbin/longest-uninterrupted-quality-run midpoint, tieearliest; newlytrainedslots5/6only0–419; no truth/similarity selection or backfill.",
            "files": {
                str(p): digest(p)
                for p in (
                    Path(__file__),
                    PROTOCOL,
                    ROOT / "recognition_temporal_review.py",
                )
            },
            "rows": selected,
        },
    )
    OUTPUT.mkdir(parents=True, exist_ok=False)
    rows = render(
        protocol, selected, {int(f["second"]): f for f in teacher["timeline"]}
    )
    sheet = Image.new("RGB", (1600, 620), "white")
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(rows):
        x, y = (i % 4) * 400, (i // 4) * 310
        draw.text(
            (x + 8, y + 5),
            f"Slot{row['track_id'] + 1} / {row['second']}s / run{row['run_start']}",
            fill="black",
        )
        for key, size, top in (("context", (384, 180), 26), ("crop", (384, 96), 210)):
            picture = ImageOps.contain(Image.open(row[key]).convert("RGB"), size)
            sheet.paste(picture, (x + 8, y + top))
    sheet.save(OUTPUT / "contact-sheet.jpg", quality=95)
    write_json(
        OUTPUT / "manifest.json",
        {
            "selection_sha256": digest(SELECTION),
            "rows": rows,
            "sheet_sha256": digest(OUTPUT / "contact-sheet.jpg"),
        },
    )
    print(json.dumps({"rows": len(rows), "sheet": str(OUTPUT / "contact-sheet.jpg")}))


if __name__ == "__main__":
    main()
