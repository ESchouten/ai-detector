"""Render bounded, model-free evidence for the 8-calves identity-label audit.

Original publisher annotations are read without executing pickle instructions.
The fixed development frames are deliberately outside reserved test windows.
No recognition predictions, masks or label corrections are used.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from annotation_audit import (
    PUBLISHER_SHA256,
    VIDEO_SHA256,
    annotated_panel,
    boxes_at,
    digest,
    publisher_arrays,
)

OVERVIEW = (0, 330, 930, 1230)
EARLY = tuple(range(0, 361, 15))
LATER = tuple(range(330, 1231, 60))
SELECTED_COWS = (5, 8, 6)


def tile(image, box, caption):
    """Preserve body proportions; a square stretch can conceal coat differences."""
    x1, y1, x2, y2 = box
    crop = image[y1:y2, x1:x2]
    height, width = crop.shape[:2]
    scale = min(220 / width, 208 / height)
    crop = cv2.resize(crop, (round(width * scale), round(height * scale)))
    height, width = crop.shape[:2]
    output = np.full((240, 240, 3), 245, np.uint8)
    left = (240 - width) // 2
    output[30 : 30 + height, left : left + width] = crop
    cv2.putText(
        output, caption, (7, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1
    )
    return output


def save(path, image):
    if not cv2.imwrite(str(path), image):
        raise OSError(f"Cannot write {path}")


def run(args):
    records = publisher_arrays(args.publisher)
    if digest(args.video) != VIDEO_SHA256:
        raise ValueError("Source video differs from the audited publisher file")
    args.output.mkdir(parents=True, exist_ok=True)
    frames, boxes, ids = {}, {}, {}
    capture = cv2.VideoCapture(str(args.video))
    seconds = sorted(set(OVERVIEW + EARLY + LATER))
    try:
        for second in seconds:
            capture.set(cv2.CAP_PROP_POS_FRAMES, second * 20)
            ok, image = capture.read()
            if not ok or image.shape[:2] != (600, 800):
                raise ValueError(f"Cannot decode expected development frame {second}")
            frames[second] = image
            ids[second], boxes[second] = boxes_at(records, second * 20 + 1, 800, 600)
    finally:
        capture.release()

    def cow_tile(second, cow):
        box = boxes[second][np.flatnonzero(ids[second] == cow)[0]]
        return tile(frames[second], box, f"{second}s / calf {cow}")

    for second in OVERVIEW:
        save(
            args.output / f"{second}-context.jpg",
            annotated_panel(
                frames[second],
                boxes[second],
                [str(cow) for cow in ids[second]],
                f"{second}s / publisher identities",
                (30, 250, 30),
            ),
        )
    save(
        args.output / "four-times-all-identities.jpg",
        np.concatenate(
            [
                np.concatenate([cow_tile(second, cow) for second in OVERVIEW], axis=1)
                for cow in range(1, 9)
            ]
        ),
    )
    for name, selected in (("early", EARLY), ("later", LATER)):
        for start in range(0, len(selected), 6):
            group = selected[start : start + 6]
            save(
                args.output / f"{name}-{group[0]:04d}.jpg",
                np.concatenate(
                    [
                        np.concatenate(
                            [cow_tile(second, cow) for cow in SELECTED_COWS], axis=1
                        )
                        for second in group
                    ]
                ),
            )
    report = {
        "source_video_sha256": VIDEO_SHA256,
        "source_annotations_sha256": PUBLISHER_SHA256,
        "scope": "Bounded visual identity continuity audit; no model predictions or relabeling",
        "overview_seconds": OVERVIEW,
        "early_seconds": EARLY,
        "later_seconds": LATER,
        "selected_cows": SELECTED_COWS,
        "reserved_windows_viewed": False,
        "rows": [
            {
                "second": second,
                "frame_id": second * 20 + 1,
                "ids": ids[second].tolist(),
                "boxes": boxes[second].tolist(),
            }
            for second in seconds
        ],
    }
    (args.output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publisher",
        type=Path,
        default=Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
    )
    parser.add_argument(
        "--video", type=Path, default=Path("datasets/8-calves/video/pmfeed_4_3_16.mp4")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/cow-identity/continuity-audit")
    )
    run(parser.parse_args())
