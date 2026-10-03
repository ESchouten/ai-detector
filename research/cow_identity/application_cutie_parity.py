"""Actual installed application adapter versus a completed same-device prefix."""

import argparse
import importlib.metadata
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

from aidetector.adapters.inference.cutie_runtime import open_cutie

ROOT = Path(__file__).parent
BASE = Path(".cache/cow-startup-propagation/streaming.json")
CLIP = Path(".cache/cow-cutie/calibration-clip")
SEED = Path(".cache/cow-startup-propagation-v3-seeds/masks.npz")
WEIGHTS = Path(".cache/cow-cutie/cutie-base-mega.pth")


def freeze(path):
    value = json.loads(BASE.read_text())
    if not value["complete"] or len(value["timeline"]) != 121:
        raise ValueError("The completed two-minute anonymous baseline is required")
    files = [
        Path(__file__),
        BASE,
        SEED,
        WEIGHTS,
        CLIP / "sampled.json",
        ROOT / "video_assessment.py",
        ROOT / "benchmark.py",
        Path("detector/src/aidetector/adapters/inference/cutie_runtime.py"),
        Path("detector/src/aidetector/adapters/inference/device.py"),
        Path("detector/vendor/cutie/cutie-1.0.0+aidetector.2-py3-none-any.whl"),
    ]
    files.extend(
        BASE.parent / "masks" / f"{row['second']}.png" for row in value["timeline"]
    )
    write_json(
        path,
        {
            "scope": "241 actual MPS CutieRuntime inputs at2Hz, source0–120. Same8anonymous initial masks. Compare every121integer mask and all object quality records exactly against completed research SDK. No YOLO execution, labels, name assignment or new accuracy claim.",
            "files": {str(p): digest(p) for p in files},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in ("torch", "numpy", "cutie", "hydra-core", "omegaconf")
            },
            "max_driver_bytes": 8 * 1024**3,
        },
    )


def checked(protocol):
    frozen = json.loads(protocol.read_text())
    for path, expected in frozen["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen parity input changed: {path}")
    if frozen["libraries"] != {
        name: importlib.metadata.version(name) for name in frozen["libraries"]
    }:
        raise ValueError("Installed runtime changed")
    return frozen


def run(protocol, output):
    import torch

    frozen = checked(protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual Metal required; CPU is not a substitute")
    torch.set_num_threads(2)
    baseline = {row["second"]: row for row in json.loads(BASE.read_text())["timeline"]}
    sources = json.loads((CLIP / "sampled.json").read_text())["rows"][:241]
    with np.load(SEED, allow_pickle=False) as data:
        planes = data["masks"]
    seed = np.where(planes.any(0), planes.argmax(0) + 1, 0).astype(np.int64)
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    report = {
        "passed": False,
        "protocol_sha256": digest(protocol),
        "matched_masks": 0,
        "processed": 0,
        "peak_driver_bytes": 0,
        "frame_seconds": [],
        "error": None,
    }
    started = time.perf_counter()
    try:
        with open_cutie(WEIGHTS, "mps") as runtime:
            for i, source in enumerate(sources):
                tick = time.perf_counter()
                ok, image = capture.read()
                if not ok or pixels_hash(image) != source["pixels_sha256"]:
                    raise ValueError("Source pixels changed")
                actual = runtime.step(
                    image,
                    mask=seed if i == 0 else None,
                    object_ids=tuple(range(1, 9)) if i == 0 else (),
                )
                second = source["second"]
                if float(second).is_integer():
                    row = baseline[int(second)]
                    expected = cv2.imread(
                        str(BASE.parent / "masks" / f"{int(second)}.png"),
                        cv2.IMREAD_UNCHANGED,
                    )
                    if not np.array_equal(actual.mask, expected):
                        raise AssertionError(f"Mask differs at {second}")
                    objects = [
                        {
                            "track_id": item.object_id - 1,
                            "area": item.area,
                            "mean_probability": item.mean_probability,
                            "p10_probability": item.p10_probability,
                        }
                        for item in actual.objects
                    ]
                    if objects != row["objects"]:
                        raise AssertionError(f"Quality evidence differs at {second}")
                    report["matched_masks"] += 1
                report["processed"] += 1
                report["frame_seconds"].append(time.perf_counter() - tick)
                report["peak_driver_bytes"] = max(
                    report["peak_driver_bytes"], torch.mps.driver_allocated_memory()
                )
                if report["peak_driver_bytes"] > frozen["max_driver_bytes"]:
                    raise RuntimeError("Frozen driver memory limit exceeded")
            report["passed"] = (
                report["matched_masks"] == 121 and report["processed"] == 241
            )
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        capture.release()
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(output, report)
        print(
            json.dumps({k: v for k, v in report.items() if k != "frame_seconds"}),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve frozen protocols")
        freeze(args.protocol)
    else:
        if args.output is None or args.output.exists():
            parser.error("Pass a new result path")
        run(args.protocol, args.output)
