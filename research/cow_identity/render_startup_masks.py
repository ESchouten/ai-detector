"""Show every actual SAM proposal without biological names or selection verdicts."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json


def tile(image, mask, box, label):
    context = image.copy()
    cv2.rectangle(
        context, (box["x1"], box["y1"]), (box["x2"], box["y2"]), (0, 220, 255), 2
    )
    foreground = np.where(mask[..., None], image, 127).astype(np.uint8)
    xs, ys = np.nonzero(mask)[1], np.nonzero(mask)[0]
    if xs.size:
        foreground = foreground[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    fitted = np.full_like(image, 127)
    scale = min(
        image.shape[1] / foreground.shape[1], image.shape[0] / foreground.shape[0]
    )
    resized = cv2.resize(
        foreground, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST
    )
    fitted[: resized.shape[0], : resized.shape[1]] = resized
    result = cv2.vconcat(
        [
            np.full((40, image.shape[1] * 2, 3), 255, np.uint8),
            cv2.hconcat([context, fitted]),
        ]
    )
    cv2.putText(
        result,
        label + " | exact source/proposal and original foreground",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 0, 0),
        1,
    )
    return result


def render(manifest_path, output):
    value = json.loads(manifest_path.read_text())
    if not value["complete"] or [r["second"] for r in value["frames"]] != [0, 0.5]:
        raise ValueError("Expected complete frozen two-frame startup control")
    output.mkdir(parents=True, exist_ok=False)
    images = []
    for index, frame in enumerate(value["frames"]):
        if (
            digest(Path(frame["masks"])) != frame["masks_sha256"]
            or digest(Path(frame["image"])) != frame["image_sha256"]
        ):
            raise ValueError("Frozen mask or source pixels changed")
        with np.load(frame["masks"], allow_pickle=False) as arrays:
            masks = arrays["original"]
        image = cv2.imread(frame["image"])
        panels = []
        for i, (mask, box) in enumerate(zip(masks, frame["proposals"], strict=True)):
            pixels = tile(image, mask, box, f"Frame{index} Candidate{i:02d}")
            path = output / f"{index}-{i:02d}.png"
            if not cv2.imwrite(str(path), pixels):
                raise OSError("Cannot save proposal review")
            images.append(
                {
                    "frame": index,
                    "proposal": i,
                    "path": str(path),
                    "sha256": digest(path),
                }
            )
            panels.append(cv2.resize(pixels, (800, 320)))
        for start in range(0, len(panels), 4):
            path = output / f"frame{index}-sheet{start // 4}.jpg"
            if not cv2.imwrite(str(path), cv2.vconcat(panels[start : start + 4])):
                raise OSError("Cannot save proposal sheet")
            images.append({"sheet": str(path), "sha256": digest(path)})
    write_json(
        output / "render.json",
        {
            "manifest_sha256": digest(manifest_path),
            "renderer_sha256": digest(Path(__file__)),
            "images": images,
            "display": "All original candidate masks, including rejected. No biological names, selection decisions or truth overlay shown. Mask views enlarged with nearest-neighbor pixels; exact raw arrays retained separately.",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.manifest, args.output)
