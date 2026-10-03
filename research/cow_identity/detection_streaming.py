"""Run the frozen tracking, corroboration and naming policy in one MPS process.

This research runner reads pixels and first-frame reviewed seeds only. Scoring
and annotation loading are separate; nothing here can change an animal's name.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_box_consensus import correspondences
from detection_cutie import (
    boxes_from_mask,
    indexed_seed,
    mask_diagnostics,
    memory_status,
    open_core,
    resource_stop,
)
from detection_cutie_variants import largest_components
from detection_quarantine_recovery import CorroboratedRecovery
from video_assessment import pixels_hash

if TYPE_CHECKING:
    from cutie.inference.inference_core import InferenceCore
    from torch import Tensor
    from ultralytics import YOLO


def validate_cadence(clip, protocol):
    expected = [
        index / protocol["processing_fps"]
        for index in range(
            protocol["last_processed_second"] * protocol["processing_fps"] + 1
        )
    ]
    if [row["second"] for row in clip["rows"]] != expected:
        raise ValueError("Source timestamps differ from the complete frozen cadence")
    if any(
        row["publisher_frame"] != round(row["second"] * clip["source_fps"]) + 1
        for row in clip["rows"]
    ):
        raise ValueError("Source frame indices differ from their timestamps")


def source_frames(capture, rows):
    """Decode one shared source frame, then discard it after both models use it."""
    for source in rows:
        ok, image = capture.read()
        if not ok or pixels_hash(image) != source["pixels_sha256"]:
            raise ValueError("Decoded source pixels differ from the frozen frame")
        yield source, image


def decide_frame(second, mask, objects, proposals, tracker, named_slots, thresholds):
    """Original mask evidence drives quarantine; LCC geometry drives pairing."""
    cleaned, _ = largest_components(mask)
    boxes = boxes_from_mask(cleaned)
    probabilities = {row["track_id"] + 1: row["p10_probability"] for row in objects}
    conflicts = tracker.observe_evidence(second, mask, probabilities, boxes, proposals)
    _, reciprocal = correspondences(boxes, proposals, thresholds["minimum_iou"])
    named = []
    for index, box in enumerate(boxes):
        slot = box["track_id"] + 1
        # A propagated mask has no object-detection class confidence. Preserve
        # the actual detector score only when it corroborates this same box.
        box["confidence"] = (
            proposals[reciprocal[index]]["confidence"] if index in reciprocal else None
        )
        if (
            slot in named_slots
            and slot not in conflicts
            and probabilities.get(slot, 0) >= thresholds["minimum_p10"]
            and index in reciprocal
        ):
            named.append(box["track_id"])
    return {
        "second": second,
        "boxes": boxes,
        "objects": objects,
        "raw_detector_boxes": proposals,
        "conflicted_ids": sorted(conflicts),
        "named_track_ids": named,
        "reciprocal_pairs": [
            {"track_id": boxes[i]["track_id"], "proposal_index": j}
            for i, j in reciprocal.items()
        ],
    }


def checked_inputs(args):
    protocol = json.loads(args.protocol.read_text())
    for path, expected in protocol["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen implementation or input changed: {path}")
    clip_path = Path(protocol["inputs"]["clip"])
    clip = json.loads((clip_path / "sampled.json").read_text())
    validate_cadence(clip, protocol)
    upstream = Path(protocol["inputs"]["upstream"])
    revision = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(upstream), "status", "--porcelain"], text=True
    ).strip()
    if revision != protocol["source_commit"] or dirty:
        raise ValueError("Cutie must use the frozen clean upstream checkout")
    libraries = {
        name: importlib.metadata.version(name) for name in protocol["libraries"]
    }
    if libraries != protocol["libraries"]:
        raise ValueError("Installed libraries differ from the frozen app runtime")
    seeds = json.loads(Path(protocol["inputs"]["seed_manifest"]).read_text())["rows"][0]
    if (
        seeds["frame"] != 1
        or [row["cow"] for row in seeds["prompts"]] != protocol["seeded_cows"]
    ):
        raise ValueError("Reviewed initial animal slots differ from the freeze")
    with np.load(protocol["inputs"]["seed_masks"], allow_pickle=False) as archive:
        masks = archive["masks"]
    count = len(protocol["seeded_cows"])
    if masks.shape != (count, clip["height"], clip["width"]) or set(
        np.unique(indexed_seed(masks))
    ) != set(range(count + 1)):
        raise ValueError("Initial masks do not preserve every original animal slot")
    return protocol, clip, masks, seeds, libraries


def detector_boxes(model, image, settings):
    prediction = model.predict(image, verbose=False, **settings)[0]
    return [
        {
            **dict(zip(("x1", "y1", "x2", "y2"), map(int, bounds), strict=True)),
            "confidence": confidence,
        }
        for bounds, confidence in zip(
            prediction.boxes.xyxy.cpu().tolist(),
            prediction.boxes.conf.cpu().tolist(),
            strict=True,
        )
    ]


def model_metadata(core, detector):
    import torch

    cutie_device = str(next(core.network.parameters()).device)
    cutie_dtype = str(next(core.network.parameters()).dtype)
    if torch.device(cutie_device).type != "mps" or cutie_dtype != "torch.float32":
        raise ValueError("Cutie must execute FP32 on MPS")
    metadata = {"cutie_device": cutie_device, "cutie_dtype": cutie_dtype}
    if detector.predictor is not None:
        metadata.update(
            yolo_device=str(detector.predictor.model.device),
            yolo_fp16=detector.predictor.model.fp16,
            class_names=detector.names,
            resolved_preprocessing={
                key: vars(detector.predictor.args)[key]
                for key in (
                    "imgsz",
                    "rect",
                    "batch",
                    "quantize",
                    "conf",
                    "iou",
                    "max_det",
                )
            },
        )
        if (
            torch.device(metadata["yolo_device"]).type != "mps"
            or not metadata["yolo_fp16"]
        ):
            raise ValueError("The corroborator must execute FP16 on MPS")
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS is required; CPU fallback invalidates this probe")
    return metadata


def run(args, protocol, clip, masks, seeds, libraries):
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable; request a hardware-enabled run")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "masks").mkdir()
    report_path = args.output / "streaming.json"
    value = {
        "complete": False,
        "stop_reason": None,
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "runner_sha256": digest(Path(__file__)),
            "source_commit": protocol["source_commit"],
            "libraries": libraries,
            "seed_prompts": seeds["prompts"],
            "smoke_frames": args.frames,
            "identity_origin": "Original reviewed first-frame slots only; no automatic re-identification or enrollment",
        },
        "timeline": [],
        "frame_seconds": [],
        "frame_samples": [],
        "memory_samples": [],
    }
    capture = None
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
        detector = YOLO(protocol["inputs"]["yolo_model"])
        value.update(config=config, model_metadata=model_metadata(core, detector))
        value["initialization_seconds"] = time.perf_counter() - started
        rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
        tracker = CorroboratedRecovery(
            rules, range(1, len(masks) + 1), protocol["recovery"]
        )
        seed = torch.from_numpy(indexed_seed(masks)).to("mps")
        capture = cv2.VideoCapture(
            str(Path(protocol["inputs"]["clip"]) / "sampled.avi")
        )
        limit = min(args.frames or len(clip["rows"]), len(clip["rows"]))
        named_slots = {
            index + 1
            for index, cow in enumerate(protocol["seeded_cows"])
            if cow in protocol["named_cows"]
        }
        pipeline = StreamingPipeline(
            core, detector, seed, tracker, named_slots, protocol, args.output
        )
        frames = iter(source_frames(capture, clip["rows"][:limit]))
        with torch.inference_mode():
            for index in range(limit):
                frame_started = time.perf_counter()
                source, image = next(frames)
                pipeline.process(source, image, index, value, frame_started)
                if index % 50 == 0 or index == limit - 1 or value["stop_reason"]:
                    value["elapsed_seconds"] = time.perf_counter() - started
                    value["quarantine_events"] = tracker.events
                    write_json(report_path, value)
                    print(
                        json.dumps(
                            {
                                "processed_frames": index + 1,
                                "second": source["second"],
                                "stop_reason": value["stop_reason"],
                                **value["memory_samples"][-1],
                            }
                        ),
                        flush=True,
                    )
                if value["stop_reason"]:
                    break
        value["complete"] = not value["stop_reason"] and len(
            value["frame_seconds"]
        ) == len(clip["rows"])
    except BaseException as error:
        # Preserve an explicitly incomplete diagnostic after interruption/native
        # SDK exceptions; the exception still reaches the caller unchanged.
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if capture is not None:
            capture.release()
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(report_path, value)


@dataclass
class StreamingPipeline:
    """One camera's GPU models and bounded temporal policy, owned by one thread."""

    core: InferenceCore
    detector: YOLO
    seed: Tensor
    tracker: CorroboratedRecovery
    named_slots: set[int]
    protocol: dict
    output: Path

    def process(self, source, image, index, value, frame_started):
        import torch

        core, detector, protocol = self.core, self.detector, self.protocol
        start = time.perf_counter()
        tensor = (
            torch.from_numpy(image[:, :, ::-1].copy())
            .permute(2, 0, 1)
            .to("mps")
            .float()
            / 255
        )
        prediction = core.step(
            tensor,
            self.seed if index == 0 else None,
            objects=list(range(1, len(protocol["seeded_cows"]) + 1))
            if index == 0
            else None,
        )
        torch.mps.synchronize()
        cutie_seconds = time.perf_counter() - start
        integer = float(source["second"]).is_integer()
        yolo_seconds = policy_seconds = 0.0
        if integer:
            second = int(source["second"])
            tick = time.perf_counter()
            proposals = detector_boxes(
                detector, image, protocol["corroborator"]["settings"]
            )
            torch.mps.synchronize()
            yolo_seconds = time.perf_counter() - tick
            tick = time.perf_counter()
            mask = core.output_prob_to_mask(prediction).cpu().numpy()
            objects = mask_diagnostics(mask, prediction.cpu().numpy())
            frame = decide_frame(
                second,
                mask,
                objects,
                proposals,
                self.tracker,
                self.named_slots,
                protocol["naming"],
            )
            path = self.output / "masks" / f"{second}.png"
            if not cv2.imwrite(str(path), mask.astype(np.uint8)):
                raise OSError("Could not cache the source-resolution original mask")
            frame.update(
                mask_sha256=digest(path),
                source_pixels_sha256=source["pixels_sha256"],
                publisher_frame=source["publisher_frame"],
            )
            value["timeline"].append(frame)
            value["model_metadata"] = model_metadata(core, detector)
            policy_seconds = time.perf_counter() - tick
        del prediction, tensor
        memory = memory_status("mps", protocol["cache_reclaim_bytes"])
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        total = time.perf_counter() - frame_started
        value["frame_seconds"].append(total)
        value["frame_samples"].append(
            {
                "second": source["second"],
                "publisher_frame": source["publisher_frame"],
                "pixels_sha256": source["pixels_sha256"],
                "decode_and_hash_seconds": start - frame_started,
                "cutie_seconds": cutie_seconds,
                "yolo_seconds": yolo_seconds,
                "policy_and_cache_seconds": policy_seconds,
                "total_seconds": total,
            }
        )
        value["memory_samples"].append(
            {
                "second": source["second"],
                **memory,
                "process_peak_rss_bytes": peak_rss,
                "working_tokens": sum(
                    t.shape[-1] for t in core.memory.work_mem.k.values()
                ),
                "long_term_tokens": sum(
                    t.shape[-1] for t in core.memory.long_mem.k.values()
                ),
            }
        )
        value["stop_reason"] = resource_stop(
            memory["mps_driver_bytes"],
            peak_rss,
            value["frame_seconds"],
            protocol["resource_limits"],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frames",
        type=int,
        help="Short hardware smoke; incomplete timelines cannot be scored",
    )
    args = parser.parse_args()
    if args.frames is not None and args.frames <= 0:
        parser.error("Smoke frame count must be positive")
    protocol, clip, masks, seeds, libraries = checked_inputs(args)
    run(args, protocol, clip, masks, seeds, libraries)


if __name__ == "__main__":
    main()
