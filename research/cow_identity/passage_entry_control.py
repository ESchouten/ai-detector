"""One reviewed initial animal, no new objects: a 22-frame lifecycle control.

The existing decision and model helpers stay immutable. Fresh detector evidence
is assessed every half second; quarantine retains its selected 1 Hz cadence.
"""

import argparse
import importlib.metadata
import json
import resource
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import (
    indexed_seed,
    mask_diagnostics,
    memory_status,
    open_core,
    resource_stop,
)
from detection_quarantine_recovery import CorroboratedRecovery
from detection_streaming import decide_frame, detector_boxes
from video_assessment import pixels_hash

from aidetector.adapters.media.images import shrink_image

ROOT = Path(__file__).parent
METHOD = ROOT / "passage_entry_protocol.json"
SEED = Path(".cache/cow-passage-entry-seed")
EXECUTION = ROOT / "passage_entry_execution.json"
OUTPUT = Path(".cache/cow-passage-entry-control")


class OneHertzQuarantine:
    """Assess current naming evidence at 2 Hz without doubling quarantine time."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.previous = None
        self.conflicts = set()

    def observe_evidence(self, second, mask, probabilities, boxes, proposals):
        expected = 0 if self.previous is None else self.previous + 0.5
        if second != expected:
            raise ValueError("Every half-second observation is required exactly once")
        self.previous = second
        if float(second).is_integer():
            self.conflicts = self.tracker.observe_evidence(
                int(second), mask, probabilities, boxes, proposals
            )
        return self.conflicts.copy()


def checked_protocol(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen lifecycle input changed: {filename}")
    manifest = json.loads(Path(protocol["inputs"]["frames"]).read_text())
    if [row["second"] for row in manifest["rows"]] != [i / 2 for i in range(22)]:
        raise ValueError("The lifecycle control must retain all 22 frozen timestamps")
    if protocol["seeded_cows"] != [5676] or protocol["dynamic_additions"]:
        raise ValueError("Only the reviewed original slot may exist in this control")
    return protocol, manifest


def source_image(row):
    path = Path(row["path"])
    if digest(path) != row["sha256"]:
        raise ValueError("Source frame file changed")
    image = cv2.imread(str(path))
    if image is None or pixels_hash(image) != row["pixels_sha256"]:
        raise ValueError("Source frame pixels changed")
    return shrink_image(image, 1280)


def runtime_contract(protocol):
    libraries = {k: importlib.metadata.version(k) for k in protocol["libraries"]}
    if libraries != protocol["libraries"]:
        raise ValueError("Installed libraries differ from the frozen app runtime")
    upstream = protocol["inputs"]["upstream"]
    revision = subprocess.check_output(
        ["git", "-C", upstream, "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", upstream, "status", "--porcelain"], text=True
    ).strip()
    if revision != protocol["source_commit"] or dirty:
        raise ValueError("Cutie checkout differs from the frozen clean revision")
    return libraries


def prepare_seed(args):
    """The model sees only frame zero and the already reviewed detector box."""
    import torch
    from ultralytics import SAM

    protocol, manifest = checked_protocol(args.protocol)
    runtime_contract(protocol)
    proposal = json.loads(Path(protocol["inputs"]["proposal"]).read_text())
    image = source_image(manifest["rows"][0])
    if pixels_hash(image) != proposal["image_pixels_sha256"]:
        raise ValueError("Seed image differs from the reviewed detector input")
    path = SEED / "masks.npz"
    if path.exists():
        raise ValueError("Preserve previous seed masks; do not reroll initialization")
    box = proposal["actual_whole_proposal"]
    bounds = [box[key] for key in ("x1", "y1", "x2", "y2")]
    torch.set_num_threads(2)
    started = time.perf_counter()
    result = SAM(protocol["inputs"]["sam_model"]).predict(
        image, bboxes=[bounds], device="cpu", imgsz=1024, verbose=False
    )[0]
    masks = result.masks.data.cpu().numpy() > 0.5
    if masks.shape != (1, 720, 1280) or not masks.any():
        raise ValueError("SAM did not return one nonempty source-resolution mask")
    np.savez_compressed(path, masks=masks)
    overlay = image.copy()
    overlay[masks[0]] = (overlay[masks[0]] * 0.6 + np.array([0, 100, 0])).astype(
        np.uint8
    )
    cv2.imwrite(str(SEED / "mask-review.png"), overlay)
    write_json(
        SEED / "mask-manifest.json",
        {
            "method_sha256": digest(args.protocol),
            "proposal_sha256": digest(Path(protocol["inputs"]["proposal"])),
            "masks_sha256": digest(path),
            "image_pixels_sha256": pixels_hash(image),
            "area": int(masks.sum()),
            "seconds": time.perf_counter() - started,
            "status": "Requires independent review before continuation",
        },
    )


def freeze_execution(args):
    protocol, _ = checked_protocol(args.protocol)
    manifest = json.loads((SEED / "mask-manifest.json").read_text())
    review = json.loads(args.review.read_text())
    if (
        manifest["method_sha256"] != digest(args.protocol)
        or manifest["masks_sha256"] != digest(SEED / "masks.npz")
        or review["method_sha256"] != digest(args.protocol)
        or review["masks_sha256"] != digest(SEED / "masks.npz")
        or review["decision"] != "accepted"
    ):
        raise ValueError("Seed review must approve these exact frozen mask pixels")
    if EXECUTION.exists():
        raise ValueError("Preserve the previous execution freeze")
    protocol["method_sha256"] = digest(args.protocol)
    protocol["inputs"]["seed_masks"] = str(SEED / "masks.npz")
    for path in (
        args.protocol,
        args.review,
        SEED / "masks.npz",
        SEED / "mask-manifest.json",
    ):
        protocol["files"][str(path)] = digest(path)
    protocol["reviewed_seed"] = review
    write_json(EXECUTION, protocol)


def process_frame(
    core, detector, seed, image, index, source, tracker, protocol, output
):
    import torch

    tensor = (
        torch.from_numpy(image[:, :, ::-1].copy()).permute(2, 0, 1).to("mps").float()
        / 255
    )
    prediction = core.step(
        tensor, seed if index == 0 else None, objects=[1] if index == 0 else None
    )
    torch.mps.synchronize()
    proposals = detector_boxes(detector, image, protocol["corroborator"]["settings"])
    torch.mps.synchronize()
    if detector.predictor.model.fp16:
        raise ValueError("Preserve the existing Purdue FP32 inference contract")
    mask = core.output_prob_to_mask(prediction).cpu().numpy()
    objects = mask_diagnostics(mask, prediction.cpu().numpy())
    frame = decide_frame(
        source["second"], mask, objects, proposals, tracker, {1}, protocol["naming"]
    )
    path = output / "masks" / f"{index:03d}.png"
    if not cv2.imwrite(str(path), mask.astype(np.uint8)):
        raise OSError("Could not cache the propagated mask")
    return {
        **frame,
        "sequence_frame": index,
        "source_frame": source["source_frame"],
        "source_pixels_sha256": source["pixels_sha256"],
        "input_pixels_sha256": pixels_hash(image),
        "mask_sha256": digest(path),
        "width": image.shape[1],
        "height": image.shape[0],
    }


def initial_model_metadata(core, detector):
    import torch

    parameters = next(core.network.parameters())
    if parameters.device.type != "mps" or parameters.dtype != torch.float32:
        raise ValueError("Cutie must preserve FP32 MPS execution")
    return {
        "cutie_device": str(parameters.device),
        "cutie_dtype": str(parameters.dtype),
        "detector_names": detector.names,
    }


def run(args):
    import torch
    from ultralytics import YOLO

    protocol, manifest = checked_protocol(args.protocol)
    libraries = runtime_contract(protocol)
    if "reviewed_seed" not in protocol or not torch.backends.mps.is_available():
        raise ValueError("An independently reviewed seed and real MPS are required")
    torch.set_num_threads(2)
    (args.output / "masks").mkdir(parents=True, exist_ok=False)
    with np.load(protocol["inputs"]["seed_masks"], allow_pickle=False) as archive:
        masks = archive["masks"]
    if masks.shape != (1, 720, 1280):
        raise ValueError("Only one original reviewed slot may be initialized")
    value = {
        "complete": False,
        "protocol_sha256": digest(args.protocol),
        "libraries": libraries,
        "timeline": [],
        "frame_seconds": [],
        "memory_samples": [],
        "stop_reason": None,
    }
    started = time.perf_counter()
    try:
        core, config = open_core(
            SimpleNamespace(
                upstream=Path(protocol["inputs"]["upstream"]),
                model=Path(protocol["inputs"]["cutie_model"]),
                device="mps",
            ),
            protocol,
        )
        model = YOLO(protocol["inputs"]["yolo_model"])
        if model.names != {0: "whole_visible_cow", 1: "coat_torso"}:
            raise ValueError("Adapted detector class semantics changed")
        value["config"] = config
        value["model_metadata"] = initial_model_metadata(core, model)
        rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
        tracker = OneHertzQuarantine(
            CorroboratedRecovery(rules, [1], protocol["recovery"])
        )
        seed = torch.from_numpy(indexed_seed(masks)).to("mps")
        with torch.inference_mode():
            for index, source in enumerate(manifest["rows"]):
                tick = time.perf_counter()
                image = source_image(source)
                frame = process_frame(
                    core,
                    model,
                    seed,
                    image,
                    index,
                    source,
                    tracker,
                    protocol,
                    args.output,
                )
                value["timeline"].append(frame)
                if model.predictor.model.device.type != "mps":
                    raise ValueError("The detector must execute on MPS")
                value["model_metadata"].update(
                    detector_device=str(model.predictor.model.device),
                    detector_fp16=model.predictor.model.fp16,
                )
                memory = memory_status("mps", protocol["cache_reclaim_bytes"])
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                    1 if sys.platform == "darwin" else 1024
                )
                value["frame_seconds"].append(time.perf_counter() - tick)
                value["memory_samples"].append(
                    {"second": source["second"], **memory, "peak_rss_bytes": rss}
                )
                value["stop_reason"] = resource_stop(
                    memory["mps_driver_bytes"],
                    rss,
                    value["frame_seconds"],
                    protocol["resource_limits"],
                )
                if value["stop_reason"]:
                    break
        value["quarantine_events"] = tracker.tracker.events
        value["complete"] = len(value["timeline"]) == 22 and not value["stop_reason"]
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "predictions.json", value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "freeze-execution", "run"))
    parser.add_argument("--protocol", type=Path, default=METHOD)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "freeze-execution" and args.review is None:
        parser.error("freeze-execution requires an independently written --review")
    {"seed": prepare_seed, "freeze-execution": freeze_execution, "run": run}[
        args.action
    ](args)
