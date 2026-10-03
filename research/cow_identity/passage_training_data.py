"""Prepare first-day public passage pixels for independent localization annotation."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from passage_runtime import LABELS, MANIFEST, PROTOCOL, materialize, sampled_frames
from PIL import Image, ImageDraw


def native_pixel_hash(image):
    return hashlib.sha256(
        str((image.shape, image.dtype)).encode() + image.tobytes()
    ).hexdigest()


def contact_sheet(rows, destination):
    width, height, columns = 640, 390, 3
    sheet = Image.new(
        "RGB", (width * columns, height * ((len(rows) + 2) // 3)), "white"
    )
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        x, y = index % columns * width, index // columns * height
        with Image.open(row["path"]) as image:
            sheet.paste(image.resize((640, 360)), (x, y))
        draw.text(
            (x + 8, y + 365), f"{row['clip']} / frame {row['frame']}", fill="black"
        )
    sheet.save(destination, quality=95)


def prepare(output):
    protocol = json.loads(PROTOCOL.read_text())
    if digest(MANIFEST) != protocol["manifest_sha256"]:
        raise ValueError("Passage source manifest changed")
    if digest(LABELS) != protocol["principal_labels_sha256"]:
        raise ValueError("Passage principal source labels changed")
    manifest = json.loads(MANIFEST.read_text())
    labels = json.loads(LABELS.read_text())["clips"]
    if (output / "manifest.json").exists():
        raise ValueError("Preserve existing annotation source manifest")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for clip in manifest["clips"]:
        if clip["role"] != "enrollment":
            continue
        cow = labels[clip["clip"]]["principal_cow"]
        if clip["date"] != "2022-06-08" or cow not in protocol["known_cows"]:
            raise ValueError("Only first-day intended-known clips may be prepared")
        source = materialize(clip, output / "clips")
        directory = output / "frames" / clip["clip"]
        directory.mkdir(parents=True, exist_ok=True)
        clip_rows = []
        for index, image in sampled_frames(clip, source, clip["width"]):
            path = directory / f"{index:06}.png"
            if not cv2.imwrite(str(path), image):
                raise OSError(f"Could not save native source frame: {path}")
            clip_rows.append(
                {
                    "clip": clip["clip"],
                    "frame": index,
                    "second": index * clip["fps_denominator"] / clip["fps_numerator"],
                    "date": clip["date"],
                    "principal_cow": cow,
                    "source_sha256": clip["sha256"],
                    "pixels_sha256": native_pixel_hash(image),
                    "path": str(path),
                    "sha256": digest(path),
                    "width": image.shape[1],
                    "height": image.shape[0],
                }
            )
        contact_sheet(clip_rows, output / f"{clip['clip']}-sheet.jpg")
        rows.extend(clip_rows)
    if len(rows) != protocol["sampling_counts"]["enrollment"]:
        raise ValueError("First-day source frame count changed")
    write_json(
        output / "manifest.json",
        {
            "purpose": "June8-only independent full-visible-animal localization annotations",
            "manifest_sha256": digest(MANIFEST),
            "principal_labels_sha256": digest(LABELS),
            "protocol_sha256": digest(PROTOCOL),
            "preparation_source_sha256": digest(Path(__file__)),
            "no_predictions": True,
            "frames": rows,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output)
