"""Render the previously selected public entry/exit sequence, with no predictions."""

import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from passage_runtime import sampled_frames
from PIL import Image, ImageDraw
from video_assessment import pixels_hash

SELECTION = Path(__file__).with_name("passage_entry_selection.json")
OUTPUT = Path(".cache/cow-passage-entry-inventory")


def render_frames(selection, hashes):
    rows = []
    for clip in selection["selected_clips"]:
        selected = [row for row in selection["rows"] if row["clip"] == clip["clip"]]
        path = (
            Path(".cache/cow-passage-torso-enrollment/clips")
            / clip["clip"]
            / "source.avi"
        )
        targets = {row["local_frame"]: row for row in selected}
        for index, image in sampled_frames(
            {**clip, "sampled_local_frame_indices": list(targets)}, path, 1920
        ):
            key = pixels_hash(image)
            if (clip["clip"], index) in hashes and key != hashes[clip["clip"], index]:
                raise ValueError(
                    "Selected pixels differ from independently reviewed source"
                )
            row = targets[index]
            target = OUTPUT / f"{row['sequence_frame']:03}.png"
            if not cv2.imwrite(str(target), image):
                raise OSError("Could not save source frame")
            rows.append(
                {
                    **row,
                    "path": str(target),
                    "pixels_sha256": key,
                    "sha256": digest(target),
                }
            )
    rows.sort(key=lambda row: row["sequence_frame"])
    if [row["sequence_frame"] for row in rows] != list(range(22)):
        raise ValueError("Selected frame sequence is incomplete")
    return rows


def render_sheets(rows):
    sheets = []
    for page, start in enumerate(range(0, len(rows), 12)):
        subset = rows[start : start + 12]
        sheet = Image.new("RGB", (1440, 300 * ((len(subset) + 2) // 3)), "white")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(subset):
            x, y = (index % 3) * 480, (index // 3) * 300
            image = Image.open(row["path"]).convert("RGB").resize((480, 270))
            sheet.paste(image, (x, y + 30))
            draw.text(
                (x + 5, y + 7),
                f"{row['second']:.1f}s / source{row['source_frame']} / local{row['local_frame']}",
                fill="black",
            )
        path = OUTPUT / f"clean-sheet-{page + 1}.jpg"
        sheet.save(path)
        sheets.append({"path": str(path), "sha256": digest(path)})
    return sheets


def main():
    selection = json.loads(SELECTION.read_text())
    for path, expected in selection["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Selected source changed: {path}")
    if OUTPUT.exists():
        raise ValueError("Preserve previous rendered source evidence")
    OUTPUT.mkdir(parents=True)
    old = json.loads(
        Path(".cache/cow-passage-firstday-annotation/manifest.json").read_text()
    )
    hashes = {
        (row["clip"], row["frame"]): row["pixels_sha256"] for row in old["frames"]
    }
    rows = render_frames(selection, hashes)
    sheets = render_sheets(rows)
    write_json(
        OUTPUT / "manifest.json",
        {
            "selection_sha256": digest(SELECTION),
            "preparer_sha256": digest(Path(__file__)),
            "source_only": True,
            "rows": rows,
            "sheets": sheets,
            "existing_annotation_pixel_hashes_checked": sum(
                (r["clip"], r["local_frame"]) in hashes for r in rows
            ),
        },
    )
    print(
        json.dumps(
            {
                "frames": len(rows),
                "selection_sha256": digest(SELECTION),
                "manifest_sha256": digest(OUTPUT / "manifest.json"),
            }
        )
    )


if __name__ == "__main__":
    cv2.setNumThreads(2)
    main()
