"""Render complete two-slot evidence from the finished frozen birth control."""

import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_entry_birth_run import PROTOCOL, checked_inputs
from passage_entry_control import source_image
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
OUTPUT = Path(".cache/cow-passage-entry-births")
COLORS = {1: (0, 220, 0), 2: (230, 120, 0)}


def render(image, mask, frame, target):
    original, overlay = image.copy(), image.copy()
    for i, box in enumerate(frame["raw_detector_boxes"]):
        corner = (box["x1"], box["y1"])
        cv2.rectangle(original, corner, (box["x2"], box["y2"]), (0, 230, 255), 3)
        cv2.putText(
            original,
            f"raw{i}:{box['confidence']:.2f}",
            corner,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 230, 255),
            2,
        )
    for slot in np.unique(mask):
        if slot:
            pixels = mask == slot
            overlay[pixels] = (
                overlay[pixels] * 0.55 + np.array(COLORS[int(slot)]) * 0.45
            ).astype(np.uint8)
    for box in frame["boxes"]:
        color = COLORS[box["track_id"] + 1]
        cv2.rectangle(overlay, (box["x1"], box["y1"]), (box["x2"], box["y2"]), color, 3)
    tile = Image.new("RGB", (1280, 430), "white")
    for x, view in ((0, original), (640, overlay)):
        tile.paste(Image.fromarray(view[:, :, ::-1]).resize((640, 360)), (x, 70))
    draw = ImageDraw.Draw(tile)
    draw.text(
        (8, 5),
        f"{frame['second']:.1f}s | named={frame['named_track_ids']} | births={frame['born_ids']} | green=original5676 slot | blue=anonymous slot",
        fill="black",
    )
    state = [
        (o["track_id"] + 1, o["area"], round(o["p10_probability"], 3))
        for o in frame["objects"]
    ]
    draw.text((8, 28), f"(stable slot, area, p10): {state}", fill="black")
    draw.text(
        (8, 48),
        "Left: original + current detector. Right: unmodified indexed masks + LCC boxes. No truth shown.",
        fill="black",
    )
    tile.save(target)


def execute():
    _, source = checked_inputs(PROTOCOL)
    value = json.loads((OUTPUT / "predictions.json").read_text())
    if not value["complete"] or value["protocol_sha256"] != digest(PROTOCOL):
        raise ValueError("Complete frozen output required")
    directory = OUTPUT / "review"
    directory.mkdir(exist_ok=False)
    records = []
    for i, (frame, row) in enumerate(
        zip(value["timeline"], source["rows"], strict=True)
    ):
        mask_path = OUTPUT / "masks" / f"{i:03d}.png"
        if digest(mask_path) != frame["mask_sha256"]:
            raise ValueError("Cached output mask changed")
        target = directory / f"{i:03d}.jpg"
        render(
            source_image(row),
            cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED),
            frame,
            target,
        )
        records.append(
            {"second": row["second"], "path": str(target), "sha256": digest(target)}
        )
    for page, start in enumerate(range(0, 22, 12)):
        rows = records[start : start + 12]
        sheet = Image.new("RGB", (1280, ((len(rows) + 1) // 2) * 215), "white")
        for i, row in enumerate(rows):
            sheet.paste(
                Image.open(row["path"]).resize((640, 215)), (i % 2 * 640, i // 2 * 215)
            )
        sheet.save(directory / f"sheet-{page + 1}.jpg")
    write_json(
        ROOT / "results/2026-10-03/purdue-entry-birth-review.json",
        {
            "scope": "Posthoc complete evidence rendering, not parameter selection",
            "sources": {
                str(p): digest(p)
                for p in (PROTOCOL, OUTPUT / "predictions.json", Path(__file__))
            },
            "rows": records,
        },
    )


if __name__ == "__main__":
    execute()
