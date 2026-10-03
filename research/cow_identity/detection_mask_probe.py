"""Inspect SAM2 cleanup with actual, imperfect detector prompts on exposed video."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pair_boxes, pixels_hash, read_frame

from aidetector.domain.models import BoundingBox


def probe(model, image, frame, output):
    boxes = [BoundingBox(**row) for row in frame["boxes"]]
    matches = pair_boxes(boxes, frame["truth"])
    prompts = [[box.x1, box.y1, box.x2, box.y2] for box in boxes]
    started = time.perf_counter()
    result = model.predict(
        image, bboxes=prompts, device="cpu", imgsz=1024, verbose=False
    )[0]
    masks = result.masks.data.cpu().numpy() > 0.5
    elapsed = time.perf_counter() - started
    rows, tiles = [], []
    for index, (box, mask) in enumerate(zip(boxes, masks, strict=True)):
        crop = image[box.y1 : box.y2, box.x1 : box.x2]
        foreground = mask[box.y1 : box.y2, box.x1 : box.x2]
        isolated = np.where(foreground[..., None], crop, 127).astype(np.uint8)
        truth = frame["truth"][matches[index]]["cow"] if index in matches else None
        tile = np.concatenate(
            [cv2.resize(value, (180, 180)) for value in (crop, isolated)], axis=1
        )
        cv2.putText(
            tile,
            f"Track {box.track_id}; GT {truth}; mask {foreground.mean():.0%}",
            (5, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 255, 255) if truth is not None else (0, 0, 255),
            1,
        )
        tiles.append(tile)
        rows.append({"prompt": prompts[index], "track": box.track_id, "truth": truth})
    if len(tiles) % 2:
        tiles.append(np.full_like(tiles[-1], 127))
    montage = np.concatenate(
        [np.concatenate(tiles[i : i + 2], axis=1) for i in range(0, len(tiles), 2)]
    )
    name = f"{frame['second']}-actual-montage.jpg"
    cv2.imwrite(str(output / name), montage)
    return {
        "second": frame["second"],
        "source_pixels_sha256": pixels_hash(image),
        "montage_sha256": digest(output / name),
        "seconds": elapsed,
        "prompts": rows,
    }


def main():
    import torch
    from ultralytics import SAM

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("timeline", "video", "model", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    timeline = json.loads(args.timeline.read_text())
    if digest(args.video) != timeline["provenance"]["video"]:
        parser.error("Unexpected video for this cached detector timeline")
    torch.set_num_threads(2)
    model = SAM(str(args.model))
    args.output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    rows = []
    try:
        for frame in timeline["timeline"]:
            if frame["second"] not in (330, 340, 350):
                continue
            _, image = read_frame(capture, frame["second"], fps)
            rows.append(probe(model, image, frame, args.output))
    finally:
        capture.release()
    write_json(
        args.output / "manifest.json",
        {
            "scope": "Visual probe using actual detector boxes, not mask accuracy or recognition",
            "timeline_sha256": digest(args.timeline),
            "model_sha256": digest(args.model),
            "device": "cpu",
            "imgsz": 1024,
            "ultralytics": __import__("ultralytics").__version__,
            "rows": rows,
        },
    )


if __name__ == "__main__":
    main()
