"""Compare local models and batch shapes through the real detector adapter.

No cameras, exporters, model downloads or application settings are touched.
Run from detector/: python -m tools.benchmark_inference --help
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter, process_time
from typing import TYPE_CHECKING, Any, cast

import cv2
import numpy as np

from aidetector.adapters.media.images import shrink_image
from aidetector.configuration import SourceConfig, YoloConfig
from aidetector.domain.models import Frame

if TYPE_CHECKING:
    from aidetector.adapters.inference.yolo import YoloDetector
    from aidetector.application.ports import Frames


def file_identity(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": path.name, "sha256": digest}


def load_frames(paths: list[Path], width: int) -> tuple[dict[str, tuple[Frame]], dict]:
    frames = {}
    read_ms = resize_ms = 0.0
    for index, path in enumerate(paths):
        started = perf_counter()
        image = cv2.imread(str(path))
        read_ms += (perf_counter() - started) * 1000
        if image is None:
            raise ValueError(f"Cannot read image: {path}")
        started = perf_counter()
        image = shrink_image(image, width)
        resize_ms += (perf_counter() - started) * 1000
        image.setflags(write=False)
        frames[str(index)] = (Frame(datetime.now(), image),)
    return frames, {"file_read_ms": read_ms, "resize_ms": resize_ms}


def batch_sources(frames: Frames, size: int, grouped: bool) -> list[tuple[str, ...]]:
    """Group only within an existing batch; never wait for more camera frames."""
    sources = tuple(frames)
    batches = []
    for offset in range(0, len(sources), size):
        window = sources[offset : offset + size]
        groups: dict[tuple[int, ...], list[str]] = {}
        for source in window:
            shape = frames[source][-1].image.shape if grouped else ()
            groups.setdefault(shape, []).append(source)
        batches.extend(tuple(group) for group in groups.values())
    return batches


def measure_pass(
    detector: YoloDetector, frames: Frames, batches: list[tuple[str, ...]]
):
    observations = {}
    cpu_started, started = process_time(), perf_counter()
    for sources in batches:
        observations.update(
            detector.detect({source: frames[source] for source in sources})
        )
    elapsed_ms = (perf_counter() - started) * 1000
    cpu_ms = (process_time() - cpu_started) * 1000
    return {"wall_ms": elapsed_ms, "cpu_ms": cpu_ms}, observations


def summarize(samples: list[dict], image_count: int) -> dict:
    wall_ms = np.array([sample["wall_ms"] for sample in samples])
    return {
        "pass_ms_p50": float(np.percentile(wall_ms, 50)),
        "pass_ms_p95": float(np.percentile(wall_ms, 95)),
        "ms_per_image": float(wall_ms.mean() / image_count),
        "images_per_second": float(image_count * 1000 / wall_ms.mean()),
        # 100% means one busy CPU core, not 100% of the whole computer.
        "cpu_percent_one_core": sum(sample["cpu_ms"] for sample in samples)
        / float(wall_ms.sum())
        * 100,
    }


def benchmark_variant(detector, frames, args, grouped, sdk_ms):
    batches = batch_sources(frames, args.batch, grouped)
    cold, _ = measure_pass(detector, frames, batches)
    for _ in range(args.warmup):
        measure_pass(detector, frames, batches)
    sdk_ms.clear()
    samples = []
    for _ in range(args.iterations):
        sample, observations = measure_pass(detector, frames, batches)
        samples.append(sample)
    return {
        "batches": batches,
        "first_pass_ms": cold["wall_ms"],
        **summarize(samples, len(frames)),
        "sdk_ms_per_image": {
            stage: elapsed / (len(frames) * args.iterations)
            for stage, elapsed in sdk_ms.items()
        },
        "predictions": {
            source: [asdict(box) for box in values[-1].boxes]
            for source, values in observations.items()
        },
    }


def benchmark_model(path: Path, config: YoloConfig, frames: Frames, args) -> dict:
    from ultralytics import YOLO

    from aidetector.adapters.inference.onnx import InferenceOptions
    from aidetector.adapters.inference.yolo import YoloDetector, initialize_predictor

    half = args.device != "cpu"
    started = perf_counter()
    model = YOLO(str(path), task=config.task)
    # SDK override values accept more than the constructor's inferred string type.
    cast(dict[str, Any], model.overrides).update(
        device=args.device, quantize=16 if half else None
    )
    options = InferenceOptions(half=half, native_mps=args.device == "mps")
    initialize_predictor(model, options, options.native_mps and path.suffix == ".pt")
    detector = YoloDetector(
        model,
        config.model_copy(update={"model": str(path)}),
        tuple(frames),
        options,
    )
    load_ms = (perf_counter() - started) * 1000
    sdk_ms: dict[str, float] = {}

    def record_speed(predictor):
        for stage, elapsed in predictor.results[0].speed.items():
            sdk_ms[stage] = sdk_ms.get(stage, 0.0) + elapsed * len(predictor.results)

    model.add_callback("on_predict_batch_end", record_speed)
    try:
        report = {
            "model": file_identity(path),
            "load_ms": load_ms,
        }
        for grouped in (False, True):
            name = "same_shape" if grouped else "arrival_order"
            report[name] = benchmark_variant(detector, frames, args, grouped, sdk_ms)
        backend = cast(Any, model.predictor).model
        report["backend"] = {
            "format": backend.format,
            "device": str(backend.device),
            "fp16": backend.fp16,
        }
        if args.data:
            # Accuracy belongs to the SDK. This compares backends at the same
            # square validation size, not live batching or event sensitivity.
            metrics = model.val(
                data=str(args.data),
                imgsz=config.imgsz,
                batch=args.batch,
                device=args.device,
                quantize=16 if half else None,
                rect=False,
                workers=0,
                plots=False,
                project=str(args.output / "validation"),
                name=path.name,
                verbose=False,
            )
            report["validation"] = {
                "metrics": metrics.results_dict,
                "per_class": json.loads(metrics.to_json()),
            }
        return report
    finally:
        model.predictor = None


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be at least 1")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        type=Path,
        required=True,
        help="Local .pt/.engine/.onnx files, in comparison order",
    )
    parser.add_argument(
        "--images",
        nargs="+",
        type=Path,
        required=True,
        help="Ordered local images representing camera batches",
    )
    parser.add_argument(
        "--preset",
        type=Path,
        help="Use its yolo settings and detection.frames_width; never open its sources",
    )
    parser.add_argument("--device", default="0", help="CUDA device index, cpu, or mps")
    parser.add_argument("--batch", type=positive_int, default=4)
    parser.add_argument("--warmup", type=positive_int, default=3)
    parser.add_argument("--iterations", type=positive_int, default=20)
    parser.add_argument(
        "--data",
        type=Path,
        help="Optional local YOLO dataset YAML for SDK accuracy validation",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New report directory"
    )
    args = parser.parse_args(argv)
    for path in [*args.models, *args.images, *filter(None, (args.preset, args.data))]:
        if not path.is_file():
            parser.error(f"Local file not found: {path}")
    if any(path.suffix not in {".pt", ".engine", ".onnx"} for path in args.models):
        parser.error("Models must be local .pt, .engine or .onnx files")
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    import torch
    import ultralytics

    preset = json.loads(args.preset.read_text()) if args.preset else {}
    config = YoloConfig.model_validate(
        {**preset.get("yolo", {}), "model": str(args.models[0])}
    )
    if config.tracking:
        raise ValueError(
            "Use untracked inference for this fixed-image benchmark; tracking requires sequential video replay"
        )
    source = SourceConfig.model_validate(
        {**preset.get("detection", {}), "source": [str(args.images[0])]}
    )
    frames, preparation = load_frames(args.images, source.frames_width)
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "ultralytics": ultralytics.__version__,
            "cuda": torch.version.cuda,
            "gpus": [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ],
        },
        "settings": config.model_dump(exclude={"model"}),
        "frames_width": source.frames_width,
        "batch": args.batch,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "images": [file_identity(path) for path in args.images],
        "preparation": preparation,
        "models": [],
    }
    for path in args.models:
        report["models"].append(benchmark_model(path, config, frames, args))
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    print(f"Report: {args.output / 'report.json'}")


if __name__ == "__main__":
    main()
