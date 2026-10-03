"""Verify the app's typed geometry against unchanged cached research decisions."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_startup_containment import containment_selection

from aidetector.adapters.inference.identity_masks import (
    foreground_boxes,
    select_startup_masks,
)
from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
STARTUP = Path(".cache/cow-startup-mask-control/manifest.json")
PROPAGATION = Path(".cache/cow-startup-propagation/streaming.json")


def run(output):
    startup = json.loads(STARTUP.read_text())
    propagation = json.loads(PROPAGATION.read_text())
    if not startup["complete"] or not propagation["complete"]:
        raise ValueError("Completed immutable caches are required")
    files = [
        Path(__file__),
        STARTUP,
        PROPAGATION,
        ROOT / "detection_startup_containment.py",
        ROOT / "detection_startup_masks.py",
        Path("detector/src/aidetector/adapters/inference/identity_masks.py"),
        Path("detector/tests/adapters/inference/test_identity_masks.py"),
    ]
    selections = []
    for frame in startup["frames"]:
        path = Path(frame["masks"])
        if digest(path) != frame["masks_sha256"]:
            raise ValueError("Startup masks changed")
        files.append(path)
        with np.load(path, allow_pickle=False) as data:
            masks = data["original"]
        old, pixels = containment_selection(masks, frame["proposals"])
        actual = select_startup_masks(
            masks, tuple(BoundingBox(**row) for row in frame["proposals"])
        )
        if (
            actual.proposal_indices != tuple(old["selected"])
            or actual.rejections
            != tuple(tuple(row["rejections"]) for row in old["rows"])
            or not np.array_equal(actual.masks, pixels[old["selected"]])
        ):
            raise AssertionError("App startup differs from frozen containment policy")
        selections.append(
            {"second": frame["second"], "selected": old["selected"], "exact": True}
        )
    count = 0
    for frame in propagation["timeline"]:
        path = PROPAGATION.parent / "masks" / f"{frame['second']}.png"
        if digest(path) != frame["mask_sha256"]:
            raise ValueError("Propagation mask changed")
        files.append(path)
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED).astype(np.int64)
        expected = tuple(
            BoundingBox(
                row["x1"],
                row["y1"],
                row["x2"],
                row["y2"],
                "cow",
                track_id=row["track_id"] + 1,
            )
            for row in frame["boxes"]
        )
        if foreground_boxes(mask, "cow") != expected:
            raise AssertionError(f"App component geometry differs at {frame['second']}")
        count += 1
    report = {
        "scope": "Code parity only: all20actual startup candidates and121cached integer-second indexed masks. No biological labels, model inference or new quality claim.",
        "passed": True,
        "startup": selections,
        "component_frames": count,
        "intentional_representation_changes": [
            "Output mask planes contain only selected candidates in original confidence order.",
            "App track IDs are stable positive object IDs; research serialization subtracts1.",
            "Mask-only class confidence remains None; the owner supplies actual detector corroboration separately.",
        ],
        "files": {str(path): digest(path) for path in files},
    }
    write_json(output, report)
    print(
        json.dumps(
            {
                "passed": True,
                "startup_frames": len(selections),
                "component_frames": count,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve completed parity reports")
    run(args.output)
