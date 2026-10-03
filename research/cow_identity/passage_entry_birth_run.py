"""A separate births-only entry replay; never acquire or change animal names."""

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
from detection_cutie import indexed_seed, memory_status, open_core, resource_stop
from detection_quarantine_recovery import CorroboratedRecovery
from detection_streaming import decide_frame, detector_boxes
from passage_entry_births import (
    birth_candidates,
    indexed_birth_masks,
    register_anonymous_objects,
    valid_birth_masks,
)
from passage_entry_control import (
    OneHertzQuarantine,
    initial_model_metadata,
    runtime_contract,
    source_image,
)
from video_assessment import pixels_hash

ROOT = Path(__file__).parent
PROTOCOL = ROOT / "passage_entry_birth_protocol.json"
OUTPUT = Path(".cache/cow-passage-entry-births")


def checked_inputs(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed frozen birth input: {filename}")
    source = json.loads(Path(protocol["inputs"]["frames"]).read_text())
    if [row["second"] for row in source["rows"]] != [i / 2 for i in range(22)]:
        raise ValueError("Every original half-second frame must be preserved")
    if protocol["seeded_cows"] != [5676] or not protocol["dynamic_additions"]:
        raise ValueError("Only the original animal may have an initial name")
    if protocol["deletion"] or protocol["births"]["name_acquisition"]:
        raise ValueError("This arm permits anonymous births only")
    return protocol, source


def advance_once(core, tensor, initial_seed, birth_masks, birth_ids):
    """One upstream time advancement, including incomplete indexed insertion."""
    import torch

    if initial_seed is not None:
        if birth_ids:
            raise ValueError("Preserve the reviewed initial seed without additions")
        return core.step(tensor, initial_seed, objects=[1], idx_mask=True)
    if birth_ids:
        indexed = torch.from_numpy(indexed_birth_masks(birth_masks, birth_ids)).to(
            tensor.device
        )
        return core.step(tensor, indexed, objects=birth_ids, idx_mask=True)
    return core.step(tensor)


def propose_masks(sam, image, proposals, mature, previous_mask, rules, output, index):
    """Current detector prompts only; save rejected as well as accepted masks."""
    if not mature:
        return np.zeros((0, *image.shape[:2]), bool), []
    ordered = sorted(
        mature, key=lambda i: tuple(proposals[i][k] for k in ("x1", "y1", "x2", "y2"))
    )
    boxes = [proposals[i] for i in ordered]
    tick = time.perf_counter()
    result = sam.predict(
        image,
        bboxes=[[box[k] for k in ("x1", "y1", "x2", "y2")] for box in boxes],
        device="cpu",
        imgsz=1024,
        verbose=False,
    )[0]
    masks = result.masks.data.cpu().numpy() > 0.5
    accepted = valid_birth_masks(masks, boxes, previous_mask, rules)
    target = output / "sam" / f"{index:03d}.npz"
    np.savez_compressed(target, masks=masks)
    return masks[accepted], [
        {
            "proposal_index": proposal,
            "box": box,
            "mask_index": i,
            "accepted": i in accepted,
            "mask_area": int(masks[i].sum()),
            "cache": str(target),
            "cache_sha256": digest(target),
            "batch_seconds": time.perf_counter() - tick,
        }
        for i, (proposal, box) in enumerate(zip(ordered, boxes, strict=True))
    ]


def process_frame(
    core, detector, sam, tracker, seed, state, row, index, protocol, output
):
    import torch

    image = source_image(row)
    proposals = detector_boxes(detector, image, protocol["corroborator"]["settings"])
    torch.mps.synchronize()
    if detector.predictor.model.device.type != "mps" or detector.predictor.model.fp16:
        raise ValueError("Preserve the fixed FP32 MPS detector contract")
    mature, state.pending = birth_candidates(
        proposals, state.boxes, state.pending, protocol["births"]
    )
    if index == 0:
        mature, state.pending = [], []
    masks, attempts = propose_masks(
        sam,
        image,
        proposals,
        mature,
        state.mask,
        protocol["births"],
        output,
        index,
    )
    ids = list(range(state.last_id + 1, state.last_id + len(masks) + 1))
    if state.last_id + len(ids) > protocol["births"]["maximum_objects"]:
        raise RuntimeError(
            "Frozen object budget exceeded; no silent deletion or ID reuse"
        )
    register_anonymous_objects(tracker.tracker, ids)
    tensor = (
        torch.from_numpy(image[:, :, ::-1].copy()).permute(2, 0, 1).to("mps").float()
        / 255
    )
    prediction = advance_once(core, tensor, seed if index == 0 else None, masks, ids)
    torch.mps.synchronize()
    if core.curr_ti != index:
        raise ValueError("Cutie must advance exactly once per source timestamp")
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
        {1},
        protocol["naming"],
    )
    if mask.max() > np.iinfo(np.uint16).max:
        raise ValueError("Stable IDs cannot wrap in the cache format")
    path = output / "masks" / f"{index:03d}.png"
    if not cv2.imwrite(str(path), mask.astype(np.uint16)):
        raise OSError("Could not cache propagated mask")
    result = {
        **frame,
        "sequence_frame": index,
        "upstream_step": core.curr_ti,
        "source_frame": row["source_frame"],
        "source_pixels_sha256": row["pixels_sha256"],
        "input_pixels_sha256": pixels_hash(image),
        "mask_sha256": digest(path),
        "width": 1280,
        "height": 720,
        "born_ids": ids,
        "object_to_channel": mapping,
        "sam_attempts": attempts,
        "pending_proposals": state.pending,
    }
    if ids:
        state.last_id = ids[-1]
    state.mask, state.boxes = mask, frame["boxes"]
    return result


def run(args):
    import torch
    from ultralytics import SAM, YOLO

    protocol, source = checked_inputs(args.protocol)
    libraries = runtime_contract(protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS is required; no implicit CPU fallback")
    torch.set_num_threads(2)
    (args.output / "masks").mkdir(parents=True, exist_ok=False)
    (args.output / "sam").mkdir()
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
        detector = YOLO(protocol["inputs"]["yolo_model"])
        if detector.names != {0: "whole_visible_cow", 1: "coat_torso"}:
            raise ValueError("Whole-animal detector class semantics changed")
        sam = SAM(protocol["inputs"]["sam_model"])
        value.update(
            config=config, model_metadata=initial_model_metadata(core, detector)
        )
        rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
        tracker = OneHertzQuarantine(
            CorroboratedRecovery(rules, [1], protocol["recovery"])
        )
        with np.load(protocol["inputs"]["seed_masks"], allow_pickle=False) as archive:
            original = archive["masks"]
        if original.shape != (1, 720, 1280):
            raise ValueError("Preserve the single reviewed original seed")
        seed = torch.from_numpy(indexed_seed(original)).to("mps")
        state = SimpleNamespace(
            mask=np.zeros((720, 1280), int), boxes=[], pending=[], last_id=1
        )
        with torch.inference_mode():
            for index, row in enumerate(source["rows"]):
                tick = time.perf_counter()
                frame = process_frame(
                    core,
                    detector,
                    sam,
                    tracker,
                    seed,
                    state,
                    row,
                    index,
                    protocol,
                    args.output,
                )
                value["timeline"].append(frame)
                memory = memory_status("mps", protocol["cache_reclaim_bytes"])
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                    1 if sys.platform == "darwin" else 1024
                )
                value["frame_seconds"].append(time.perf_counter() - tick)
                value["memory_samples"].append(
                    {"second": row["second"], **memory, "peak_rss_bytes": rss}
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
        value["model_metadata"].update(
            detector_device=str(detector.predictor.model.device),
            detector_fp16=detector.predictor.model.fp16,
        )
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "predictions.json", value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    run(parser.parse_args())
