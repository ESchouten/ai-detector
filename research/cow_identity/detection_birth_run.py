"""Frozen crowded anonymous births using cached detector evidence, not live FPS."""

import argparse
import json
import resource
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from benchmark import digest, write_json
from cutie_object_state import stable_mask_diagnostics
from detection_birth_cache import checked_inputs as checked_cache_inputs
from detection_cutie import indexed_seed, memory_status, open_core, resource_stop
from detection_quarantine_recovery import CorroboratedRecovery
from detection_streaming import decide_frame, source_frames
from passage_entry_birth_run import advance_once, propose_masks
from passage_entry_births import birth_candidates, register_anonymous_objects
from passage_entry_control import OneHertzQuarantine, runtime_contract

ROOT = Path(__file__).parent
PROTOCOL = ROOT / "detection_birth_protocol.json"
OUTPUT = Path(".cache/cow-cutie/crowded-births")


def checked_inputs(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed frozen dynamic input: {filename}")
    _, clip, baseline = checked_cache_inputs(Path(protocol["inputs"]["cache_protocol"]))
    proposals = json.loads(Path(protocol["inputs"]["proposals"]).read_text())
    if not proposals["complete"] or proposals["protocol_sha256"] != digest(
        Path(protocol["inputs"]["cache_protocol"])
    ):
        raise ValueError("A complete frozen detector cache is required")
    if (
        protocol["seeded_cows"] != list(range(1, 7))
        or not protocol["dynamic_additions"]
        or protocol["deletion"]
    ):
        raise ValueError("Only six original names and anonymous births are allowed")
    for row, candidate in zip(clip["rows"], proposals["timeline"], strict=True):
        if (
            any(candidate[key] != row[key] for key in ("second", "publisher_frame"))
            or candidate["source_pixels_sha256"] != row["pixels_sha256"]
        ):
            raise ValueError("Cached proposal source or timestamp differs")
    seeds = json.loads(Path(protocol["inputs"]["seed_manifest"]).read_text())["rows"][0]
    if seeds["prompts"] != baseline["provenance"]["seed_prompts"]:
        raise ValueError("Original reviewed seed labels changed")
    return protocol, clip, seeds, proposals


def process_frame(
    core, sam, tracker, seed, state, image, row, index, cached, protocol, output
):
    import torch

    proposals = cached["boxes"]
    mature, state.pending = birth_candidates(
        proposals, state.boxes, state.pending, protocol["births"]
    )
    if index == 0:
        mature, state.pending = [], []
    masks, attempts = propose_masks(
        sam, image, proposals, mature, state.mask, protocol["births"], output, index
    )
    ids = list(range(state.last_id + 1, state.last_id + len(masks) + 1))
    if state.last_id + len(ids) > protocol["births"]["maximum_objects"]:
        write_json(
            output / "budget-stop.json",
            {
                "second": row["second"],
                "existing_ids": list(tracker.tracker.object_ids),
                "proposed_ids": ids,
                "attempts": attempts,
            },
        )
        raise RuntimeError(
            "Frozen eight-object budget exceeded; no deletion, reuse or ignored birth"
        )
    register_anonymous_objects(tracker.tracker, ids)
    tensor = (
        torch.from_numpy(image[:, :, ::-1].copy()).permute(2, 0, 1).to("mps").float()
        / 255
    )
    if index == 0:
        prediction = core.step(tensor, seed, objects=list(range(1, 7)), idx_mask=True)
    else:
        prediction = advance_once(core, tensor, None, masks, ids)
    torch.mps.synchronize()
    if core.curr_ti != index:
        raise ValueError("Exactly one Cutie step per source timestamp is required")
    mask = core.output_prob_to_mask(prediction).cpu().numpy()
    mapping = {
        i: core.object_manager.find_tmp_by_id(i)
        for i in core.object_manager.all_obj_ids
    }
    objects = stable_mask_diagnostics(mask, prediction.cpu().numpy(), mapping)
    frame = decide_frame(
        row["second"],
        mask,
        objects,
        proposals,
        tracker,
        set(range(1, 7)),
        protocol["naming"],
    )
    path = output / "masks" / f"{row['second']:g}.png"
    if mask.max() > np.iinfo(np.uint16).max or not cv2.imwrite(
        str(path), mask.astype(np.uint16)
    ):
        raise OSError("Could not preserve the stable indexed mask")
    state.mask, state.boxes = mask, frame["boxes"]
    if ids:
        state.last_id = ids[-1]
    return {
        **frame,
        "publisher_frame": row["publisher_frame"],
        "source_pixels_sha256": row["pixels_sha256"],
        "mask_sha256": digest(path),
        "born_ids": ids,
        "object_to_channel": mapping,
        "sam_attempts": attempts,
        "pending_proposals": state.pending,
        "upstream_step": core.curr_ti,
    }


def execute_frames(args, protocol, clip, value, core, sam, tracker, proposals):
    import torch

    with np.load(protocol["inputs"]["seed_masks"], allow_pickle=False) as archive:
        masks = archive["masks"]
    if masks.shape != (6, clip["height"], clip["width"]):
        raise ValueError("Exact six reviewed source-sized masks required")
    seed = torch.from_numpy(indexed_seed(masks)).to("mps")
    state = SimpleNamespace(
        mask=np.zeros((clip["height"], clip["width"]), int),
        boxes=[],
        pending=[],
        last_id=6,
    )
    capture = cv2.VideoCapture(str(Path(protocol["inputs"]["clip"]) / "sampled.avi"))
    try:
        with torch.inference_mode():
            for index, ((row, image), cached) in enumerate(
                zip(
                    source_frames(capture, clip["rows"]),
                    proposals["timeline"],
                    strict=True,
                )
            ):
                tick = time.perf_counter()
                frame = process_frame(
                    core,
                    sam,
                    tracker,
                    seed,
                    state,
                    image,
                    row,
                    index,
                    cached,
                    protocol,
                    args.output,
                )
                value["all_frames"].append(frame)
                if float(row["second"]).is_integer():
                    value["timeline"].append(frame)
                value["frame_seconds"].append(time.perf_counter() - tick)
                memory = memory_status("mps", protocol["cache_reclaim_bytes"])
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                    1 if sys.platform == "darwin" else 1024
                )
                value["memory_samples"].append(
                    {
                        "second": row["second"],
                        **memory,
                        "process_peak_rss_bytes": rss,
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
                    rss,
                    value["frame_seconds"],
                    protocol["resource_limits"],
                )
                if index % 50 == 0:
                    write_json(args.output / "streaming.json", value)
                    print(
                        json.dumps(
                            {
                                "processed_frames": index + 1,
                                "second": row["second"],
                                "objects": len(tracker.tracker.object_ids),
                                "driver_bytes": memory["mps_driver_bytes"],
                                "stop_reason": value["stop_reason"],
                            }
                        ),
                        flush=True,
                    )
                if value["stop_reason"]:
                    break
    finally:
        capture.release()


def run(args):
    import torch
    from ultralytics import SAM

    protocol, clip, seeds, proposals = checked_inputs(args.protocol)
    libraries = runtime_contract(protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS required for frozen crowded propagation")
    torch.set_num_threads(2)
    (args.output / "masks").mkdir(parents=True, exist_ok=False)
    (args.output / "sam").mkdir()
    value = {
        "complete": False,
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "libraries": libraries,
            "seed_prompts": seeds["prompts"],
            "detector_cache_sha256": digest(Path(protocol["inputs"]["proposals"])),
            "performance_scope": "Cached detector evidence; propagation plus same-frame SAM timing is not complete live performance",
        },
        "timeline": [],
        "all_frames": [],
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
        parameter = next(core.network.parameters())
        if parameter.device.type != "mps" or parameter.dtype != torch.float32:
            raise ValueError("Cutie must retain FP32 MPS execution")
        sam = SAM(protocol["inputs"]["sam_model"])
        rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
        tracker = OneHertzQuarantine(
            CorroboratedRecovery(rules, range(1, 7), protocol["recovery"])
        )
        value.update(
            config=config,
            model_metadata={
                "cutie_device": str(parameter.device),
                "cutie_dtype": str(parameter.dtype),
                "sam_device": "cpu",
                "detector": proposals["model_metadata"],
            },
        )
        value["initialization_seconds"] = time.perf_counter() - started
        execute_frames(args, protocol, clip, value, core, sam, tracker, proposals)
        value["quarantine_events"] = tracker.tracker.events
        value["complete"] = (
            len(value["all_frames"]) == 3059
            and len(value["timeline"]) == 1530
            and not value["stop_reason"]
        )
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "streaming.json", value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    run(parser.parse_args())
