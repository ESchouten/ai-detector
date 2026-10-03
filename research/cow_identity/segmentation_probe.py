"""Inspect box-prompted SAM masks on three exposed development frames.

This is a crop-cleanup diagnostic, not a detector or identity evaluation.
Publisher boxes supply prompts; identity labels are only montage captions.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import annotations, pixels_hash, read_frame, truth_at


def run(args):
    import torch
    from ultralytics import SAM

    torch.set_num_threads(2)
    records, metadata = annotations(args)
    args.output.mkdir(parents=True, exist_ok=True)
    model = SAM(str(args.model))
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    rows = []
    try:
        for second in (0, 330, 930):
            frame, image = read_frame(capture, second, fps)
            height, width = image.shape[:2]
            truth = truth_at(records, frame, width, height)
            started = time.perf_counter()
            result = model.predict(
                image,
                bboxes=[item["box"] for item in truth],
                device=args.device,
                imgsz=1024,
                verbose=False,
            )[0]
            masks = result.masks.data.cpu().numpy() > 0.5
            if masks.shape != (len(truth), height, width):
                raise ValueError(f"Unexpected mask dimensions: {masks.shape}")
            elapsed = time.perf_counter() - started
            np.savez_compressed(args.output / f"{second}-masks.npz", masks=masks)
            tiles = []
            for item, mask in zip(truth, masks, strict=True):
                x1, y1, x2, y2 = item["box"]
                crop = image[y1:y2, x1:x2]
                foreground = mask[y1:y2, x1:x2]
                isolated = np.where(foreground[..., None], crop, 127).astype(np.uint8)
                tile = np.concatenate(
                    [cv2.resize(value, (180, 180)) for value in (crop, isolated)],
                    axis=1,
                )
                cv2.putText(
                    tile,
                    f"ID {item['cow']}; mask {foreground.mean():.0%}",
                    (5, 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 255, 255),
                    1,
                )
                tiles.append(tile)
            montage = np.concatenate(
                [np.concatenate(tiles[i : i + 2], axis=1) for i in range(0, 8, 2)]
            )
            cv2.imwrite(str(args.output / f"{second}-montage.jpg"), montage)
            rows.append(
                {
                    "second": second,
                    "frame": frame,
                    "source_pixels_sha256": pixels_hash(image),
                    "prompts": truth,
                    "mask_file_sha256": digest(args.output / f"{second}-masks.npz"),
                    "seconds": elapsed,
                }
            )
            print(json.dumps({"second": second, "elapsed": elapsed}), flush=True)
    finally:
        capture.release()
    write_json(
        args.output / "manifest.json",
        {
            "video_sha256": digest(args.video),
            "annotations": metadata,
            "sam_sha256": digest(args.model),
            "ultralytics_version": __import__("ultralytics").__version__,
            "device": args.device,
            "imgsz": 1024,
            "background": 127,
            "scope": "Oracle box prompts on development frames only",
            "rows": rows,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source-pickle", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
