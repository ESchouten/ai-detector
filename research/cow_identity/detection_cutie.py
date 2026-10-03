"""Frozen Cutie streaming control; run in its separate upstream research environment."""

import argparse
import hashlib
import importlib.metadata
import json
import resource
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from benchmark import digest, write_json

PROTOCOL = Path(__file__).with_name("detection_cutie_protocol.json")


def resource_stop(driver, peak_rss, durations, limits):
    if driver > limits["max_mps_driver_bytes"]:
        return "MPS driver allocation exceeded the frozen memory budget"
    if peak_rss > limits["max_peak_rss_bytes"]:
        return "Process resident memory exceeded the frozen budget"
    window = limits["timing_window_frames"]
    if (
        len(durations) >= limits["warmup_frames"] + window
        and np.mean(durations[-window:]) > limits["max_mean_seconds_per_frame"]
    ):
        return "Sustained inference exceeded the frozen frame-time budget"
    return None


def indexed_seed(masks):
    """Retain original object slots when overlapping masks need one pixel owner."""
    return np.where(masks.any(0), masks.argmax(0) + 1, 0).astype(np.int64)


def boxes_from_mask(mask):
    boxes = []
    for object_id in np.unique(mask):
        if object_id == 0:
            continue
        ys, xs = np.nonzero(mask == object_id)
        if xs.min() == xs.max() or ys.min() == ys.max():
            continue
        boxes.append(
            dict(
                x1=int(xs.min()),
                y1=int(ys.min()),
                x2=int(xs.max()),
                y2=int(ys.max()),
                label="cow",
                confidence=1.0,
                track_id=int(object_id) - 1,
            )
        )
    return boxes


def mask_diagnostics(mask, probabilities):
    """Cache small uncertainty summaries; later analysis never needs GPU replay."""
    objects = []
    for box in boxes_from_mask(mask):
        object_id = box["track_id"] + 1
        pixels = mask == object_id
        confidence = probabilities[object_id][pixels]
        objects.append(
            dict(
                track_id=box["track_id"],
                area=int(pixels.sum()),
                mean_probability=float(confidence.mean()),
                p10_probability=float(np.quantile(confidence, 0.1)),
            )
        )
    return objects


def memory_status(device, reclaim_bytes):
    import torch

    if device != "mps":
        return dict(mps_driver_bytes=0, mps_allocated_bytes=0)
    before = torch.mps.driver_allocated_memory()
    if reclaim_bytes is not None and before > reclaim_bytes:
        torch.mps.synchronize()
        torch.mps.empty_cache()
    return dict(
        mps_driver_bytes=torch.mps.driver_allocated_memory(),
        mps_driver_before_reclaim_bytes=before,
        mps_allocated_bytes=torch.mps.current_allocated_memory(),
    )


def record_frame(args, source, core, prediction, protocol):
    mask = core.output_prob_to_mask(prediction).cpu().numpy()
    if not float(source["second"]).is_integer():
        return None
    frame = dict(second=int(source["second"]), boxes=boxes_from_mask(mask))
    if protocol.get("cache_masks"):
        directory = args.output / "masks"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{frame['second']}.png"
        if not cv2.imwrite(str(path), mask.astype(np.uint8)):
            raise ValueError("Could not save the source-resolution indexed mask")
        frame["mask_sha256"] = digest(path)
        frame["objects"] = mask_diagnostics(mask, prediction.cpu().numpy())
    return frame


def open_core(args, protocol):
    import torch
    from cutie.inference.inference_core import InferenceCore
    from cutie.model.cutie import CUTIE
    from cutie.model.utils import resnet
    from hydra import compose, initialize_config_dir
    from omegaconf import OmegaConf

    with initialize_config_dir(
        version_base="1.3.2", config_dir=str(args.upstream.resolve() / "cutie/config")
    ):
        config = compose(config_name="eval_config")
        for key in ("max_internal_size", "mem_every", "use_long_term"):
            config[key] = protocol[key]
        # The complete checkpoint supplies every parameter. Avoid downloading
        # redundant ImageNet initialization through the upstream constructors.
        with (
            patch.object(
                resnet,
                "resnet18",
                lambda pretrained=True, extra_dim=0, model_dir=None: resnet.ResNet(
                    resnet.BasicBlock, [2, 2, 2, 2], extra_dim
                ),
            ),
            patch.object(
                resnet,
                "resnet50",
                lambda pretrained=True, extra_dim=0, model_dir=None: resnet.ResNet(
                    resnet.Bottleneck, [3, 4, 6, 3], extra_dim
                ),
            ),
        ):
            model = CUTIE(config).eval()
        model.load_state_dict(
            torch.load(args.model, map_location="cpu", weights_only=True), strict=True
        )
        model.to(args.device)
        return InferenceCore(model, config), OmegaConf.to_container(
            config, resolve=True
        )


def propagate(args, protocol, clip, masks, provenance):
    import torch

    torch.set_num_threads(2)
    initializing = time.perf_counter()
    core, config = open_core(args, protocol)
    initialization_seconds = time.perf_counter() - initializing
    seed = torch.from_numpy(indexed_seed(masks)).to(args.device)
    capture = cv2.VideoCapture(str(args.clip / "sampled.avi"))
    limit = min(args.frames or len(clip["rows"]), len(clip["rows"]))
    value = dict(
        provenance=provenance,
        config=config,
        complete=False,
        timeline=[],
        frame_seconds=[],
        memory_samples=[],
        stop_reason=None,
        actual_device=str(next(core.network.parameters()).device),
        parameter_dtype=str(next(core.network.parameters()).dtype),
        initialization_seconds=initialization_seconds,
    )
    started = time.perf_counter()
    peak = 0
    try:
        with torch.inference_mode():
            for index, source in enumerate(clip["rows"][:limit]):
                frame_started = time.perf_counter()
                ok, image = capture.read()
                if not ok:
                    raise ValueError("Sampled clip ended before its timestamp manifest")
                pixels = hashlib.sha256(str((image.shape, image.dtype)).encode())
                pixels.update(image.tobytes())
                if pixels.hexdigest() != source["pixels_sha256"]:
                    raise ValueError(
                        "Sampled pixels differ from the frozen source frame"
                    )
                tensor = torch.from_numpy(image[:, :, ::-1].copy()).permute(2, 0, 1)
                tensor = tensor.to(args.device).float() / 255
                prediction = core.step(
                    tensor,
                    seed if index == 0 else None,
                    objects=list(range(1, 9)) if index == 0 else None,
                )
                frame = record_frame(args, source, core, prediction, protocol)
                if frame is not None:
                    value["timeline"].append(frame)
                memory = memory_status(args.device, protocol.get("cache_reclaim_bytes"))
                driver = memory["mps_driver_bytes"]
                value["frame_seconds"].append(time.perf_counter() - frame_started)
                peak = max(peak, driver)
                peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                    1 if sys.platform == "darwin" else 1024
                )
                value["stop_reason"] = resource_stop(
                    driver,
                    peak_rss,
                    value["frame_seconds"],
                    protocol["resource_limits"],
                )
                if index % 50 == 0 or index == limit - 1 or value["stop_reason"]:
                    sample = dict(
                        second=source["second"],
                        **memory,
                        process_peak_rss_bytes=peak_rss,
                        working_tokens=sum(
                            t.shape[-1] for t in core.memory.work_mem.k.values()
                        ),
                        long_term_tokens=sum(
                            t.shape[-1] for t in core.memory.long_mem.k.values()
                        ),
                    )
                    value["memory_samples"].append(sample)
                    value["elapsed_seconds"] = time.perf_counter() - started
                    value["peak_observed_mps_driver_bytes"] = peak
                    write_json(args.output / "propagation.json", value)
                    print(
                        json.dumps(dict(processed_frames=index + 1, **sample)),
                        flush=True,
                    )
                if value["stop_reason"]:
                    break
        value["complete"] = not value["stop_reason"] and len(
            value["frame_seconds"]
        ) == len(clip["rows"])
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "propagation.json", value)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "model", "clip", "seed-masks", "seed-manifest", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    parser.add_argument(
        "--frames",
        type=int,
        help="Short smoke only; incomplete timelines cannot be scored",
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    for path, key in (
        (args.model, "model_sha256"),
        (args.seed_masks, "seed_masks_sha256"),
        (args.seed_manifest, "seed_manifest_sha256"),
        (args.clip / "sampled.avi", "sampled_clip_sha256"),
        (args.clip / "sampled.json", "sampled_manifest_sha256"),
    ):
        if digest(path) != protocol[key]:
            parser.error(f"Unexpected source for {key}")
    revision = subprocess.check_output(
        ["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    if (
        revision != protocol["source_commit"]
        or subprocess.check_output(
            ["git", "-C", str(args.upstream), "status", "--porcelain"], text=True
        ).strip()
    ):
        parser.error(
            "Cutie checkout must exactly match the frozen clean upstream revision"
        )
    clip = json.loads((args.clip / "sampled.json").read_text())
    manifest = json.loads(args.seed_manifest.read_text())
    seeds = manifest["rows"][0]
    if (
        seeds["frame"] != 1
        or [row["cow"] for row in seeds["prompts"]] != protocol["seeded_cows"]
    ):
        parser.error("Seed object order differs from the frozen initial frame")
    with np.load(args.seed_masks, allow_pickle=False) as archive:
        masks = archive["masks"]
    if masks.shape != (8, clip["height"], clip["width"]) or set(
        np.unique(indexed_seed(masks))
    ) != set(range(9)):
        parser.error("Seed masks must contain all eight original object slots")
    provenance = dict(
        runner_sha256=digest(Path(__file__)),
        protocol_sha256=digest(args.protocol),
        source_commit=revision,
        seed_prompts=seeds["prompts"],
        device=args.device,
        smoke_frames=args.frames,
        libraries={
            name: importlib.metadata.version(name)
            for name in ("torch", "torchvision", "numpy", "hydra-core", "einops")
        },
    )
    if (args.output / "propagation.json").exists():
        parser.error(
            "Output already exists; score the cached timeline or select a fresh directory"
        )
    propagate(args, protocol, clip, masks, provenance)


if __name__ == "__main__":
    main()
