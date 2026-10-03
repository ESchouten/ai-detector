"""Check actual CPU segmentation through the application against frozen seeds."""

import argparse
import importlib.metadata
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_startup_containment import containment_selection
from video_assessment import pixels_hash

from aidetector.adapters.inference.identity_startup import segment_startup
from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
STARTUP = Path(".cache/cow-startup-mask-control/manifest.json")
WEIGHTS = Path(".cache/cow-segmentation/sam2.1_t.pt")


def freeze(path):
    original = json.loads(STARTUP.read_text())
    if not original["complete"] or len(original["frames"]) != 2:
        raise ValueError("Use both completed original source frames")
    files = [
        Path(__file__),
        STARTUP,
        WEIGHTS,
        ROOT / "benchmark.py",
        ROOT / "video_assessment.py",
        ROOT / "detection_startup_containment.py",
        ROOT / "detection_startup_masks.py",
        Path("detector/src/aidetector/domain/models.py"),
        Path("detector/src/aidetector/adapters/inference/identity_startup.py"),
        Path("detector/src/aidetector/adapters/inference/identity_masks.py"),
    ]
    for frame in original["frames"]:
        for key in ("image", "masks"):
            file = Path(frame[key])
            if digest(file) != frame[f"{key}_sha256"]:
                raise ValueError("Original source or mask changed")
            files.append(file)
    write_json(
        path,
        {
            "files": {str(p): digest(p) for p in files},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in ("torch", "torchvision", "ultralytics", "numpy", "Pillow")
            },
            "scope": "Actual app CPU FP32 SAM2.1 initialization and containment against all20 original same-frame proposals. No labels, naming, threshold selection or new quality claim.",
            "weights": str(WEIGHTS),
            "original": str(STARTUP),
            "criteria": "Selected original proposal indices, all rejection reasons and every selected mask pixel must match exactly on both source frames.",
        },
    )


def run(protocol_path, output):
    import torch

    protocol = json.loads(protocol_path.read_text())
    for path, expected in protocol["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen source changed: {path}")
    if any(
        importlib.metadata.version(k) != v for k, v in protocol["libraries"].items()
    ):
        raise ValueError("Frozen runtime changed")
    torch.set_num_threads(2)
    original = json.loads(Path(protocol["original"]).read_text())
    reports = []
    for frame in original["frames"]:
        image = cv2.imread(frame["image"])
        if pixels_hash(image) != frame["source_pixels_sha256"]:
            raise ValueError("Source pixels changed")
        with np.load(frame["masks"], allow_pickle=False) as archive:
            expected, planes = containment_selection(
                archive["original"], frame["proposals"]
            )
        started = perf_counter()
        actual = segment_startup(
            Path(protocol["weights"]),
            image,
            tuple(BoundingBox(**row) for row in frame["proposals"]),
        )
        exact = (
            actual.proposal_indices == tuple(expected["selected"])
            and actual.rejections
            == tuple(tuple(r["rejections"]) for r in expected["rows"])
            and np.array_equal(actual.masks, planes[expected["selected"]])
        )
        reports.append(
            {
                "second": frame["second"],
                "proposals": len(frame["proposals"]),
                "selected": actual.proposal_indices,
                "exact": exact,
                "elapsed_seconds": perf_counter() - started,
            }
        )
    report = {
        "protocol_sha256": digest(protocol_path),
        "frames": reports,
        "passed": all(row["exact"] for row in reports),
        "scope": protocol["scope"],
    }
    write_json(output, report)
    print(json.dumps(report))
    if not report["passed"]:
        raise AssertionError("App startup segmentation differs from frozen seeds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.protocol if args.mode == "freeze" else args.output
    if destination is None or destination.exists():
        parser.error("Provide a new output path; preserve completed evidence")
    if args.mode == "freeze":
        freeze(args.protocol)
    else:
        run(args.protocol, args.output)
