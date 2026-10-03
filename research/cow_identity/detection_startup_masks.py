"""One fixed two-frame, anonymous startup control from every actual proposal."""

import argparse
import importlib.metadata
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

ROOT = Path(__file__).parent
CLIP = Path(".cache/cow-cutie/calibration-clip")
PROPOSALS = Path(".cache/cow-cutie/birth-proposals.json")
SAM = Path(".cache/cow-segmentation/sam2.1_t.pt")
RULES = {
    "minimum_prompt_support": 0.9,
    "duplicate_mask_iou": 0.8,
    "maximum_remaining_overlap": 0.1,
    "temporal_mask_iou": 0.5,
}


def mask_iou(left, right):
    intersection = int(np.count_nonzero(left & right))
    union = int(np.count_nonzero(left | right))
    return intersection / union if union else 0.0


def select_masks(masks, proposals, rules):
    """Keep rejection provenance; never infer names or edit the original masks."""
    if masks.dtype != bool or masks.ndim != 3 or len(masks) != len(proposals):
        raise ValueError("One original boolean mask per proposal is required")
    order = sorted(
        range(len(proposals)), key=lambda i: (-proposals[i]["confidence"], i)
    )
    rows, kept = [], []
    for i, box in enumerate(proposals):
        area = int(masks[i].sum())
        support = (
            int(masks[i, box["y1"] : box["y2"], box["x1"] : box["x2"]].sum()) / area
            if area
            else 0.0
        )
        rows.append(
            {
                "proposal": i,
                "area": area,
                "prompt_support": support,
                "rejections": ["empty_mask"]
                if not area
                else ["prompt_support"]
                if support < rules["minimum_prompt_support"]
                else [],
            }
        )
    for i in order:
        if rows[i]["rejections"]:
            continue
        duplicate = next(
            (
                j
                for j in kept
                if mask_iou(masks[i], masks[j]) >= rules["duplicate_mask_iou"]
            ),
            None,
        )
        if duplicate is not None:
            rows[i]["rejections"].append("duplicate_mask")
            rows[i]["suppressed_by"] = duplicate
        else:
            kept.append(i)
    ambiguous = remaining_ambiguity(
        masks, kept, rows, rules["maximum_remaining_overlap"]
    )
    for i in {index for pair in ambiguous for index in (pair["left"], pair["right"])}:
        rows[i]["rejections"].append("ambiguous_overlap")
    selected, occupied = [], np.zeros(masks.shape[1:], bool)
    disjoint = np.zeros_like(masks)
    for i in kept:
        if rows[i]["rejections"]:
            continue
        disjoint[i] = masks[i] & ~occupied
        occupied |= disjoint[i]
        selected.append(i)
        rows[i]["assigned_area"] = int(disjoint[i].sum())
    return {
        "rows": rows,
        "confidence_order": order,
        "selected": selected,
        "ambiguous_pairs": ambiguous,
    }, disjoint


def remaining_ambiguity(masks, kept, rows, maximum_overlap):
    pairs = []
    for index, i in enumerate(kept):
        for j in kept[index + 1 :]:
            overlap = int(np.count_nonzero(masks[i] & masks[j])) / min(
                rows[i]["area"], rows[j]["area"]
            )
            if overlap > maximum_overlap:
                pairs.append({"left": i, "right": j, "overlap_of_smaller": overlap})
    return pairs


def temporal_matches(previous, current, old_ids, new_ids, minimum_iou):
    edges = [
        (i, j, mask_iou(previous[i], current[j]))
        for i in old_ids
        for j in new_ids
        if mask_iou(previous[i], current[j]) >= minimum_iou
    ]
    matched = [
        {"previous_proposal": i, "current_proposal": j, "mask_iou": overlap}
        for i, j, overlap in edges
        if sum(a == i for a, _, _ in edges) == 1
        and sum(b == j for _, b, _ in edges) == 1
    ]
    return {
        "edges": [
            {"previous_proposal": i, "current_proposal": j, "mask_iou": v}
            for i, j, v in edges
        ],
        "matched": matched,
        "unconfirmed_current": [
            j for j in new_ids if j not in {m["current_proposal"] for m in matched}
        ],
    }


def libraries():
    return {
        name: importlib.metadata.version(name)
        for name in ("torch", "torchvision", "ultralytics", "numpy", "Pillow")
    }


def inputs():
    clip = json.loads((CLIP / "sampled.json").read_text())
    value = json.loads(PROPOSALS.read_text())
    if not value["complete"]:
        raise ValueError("Use completed actual detector proposals")
    selected = value["timeline"][:2]
    source = clip["rows"][:2]
    if [r["second"] for r in selected] != [0, 0.5] or [r["second"] for r in source] != [
        0,
        0.5,
    ]:
        raise ValueError("The control uses only first source frames0/0.5")
    for row, original in zip(selected, source, strict=True):
        if (
            row["source_pixels_sha256"] != original["pixels_sha256"]
            or row["publisher_frame"] != original["publisher_frame"]
        ):
            raise ValueError("Proposal and source pixels differ")
    return clip, selected


def freeze(output):
    clip, selected = inputs()
    files = [
        Path(__file__),
        ROOT / "test_detection_startup_masks.py",
        ROOT / "benchmark.py",
        ROOT / "video_assessment.py",
        PROPOSALS,
        CLIP / "sampled.json",
        CLIP / "sampled.avi",
        SAM,
        ROOT / "detection_birth_cache_protocol.json",
    ]
    write_json(
        output,
        {
            "status": "FROZEN_ANONYMOUS_STARTUP_CONTROL_PENDING_CPU_INFERENCE",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {str(p): digest(p) for p in files},
            "source_video_sha256": clip["contract"]["video_sha256"],
            "seconds": [0, 0.5],
            "source_rows": clip["rows"][:2],
            "proposal_rows": selected,
            "rules": RULES,
            "libraries": libraries(),
            "opencv": cv2.__version__,
            "sam_settings": {"device": "cpu", "imgsz": 1024, "quantize": 32},
            "sam": str(SAM),
            "clip": str(CLIP / "sampled.avi"),
            "order": "Preserve every raw same-frame proposal. Support gate, greedy maskIoU NMS by detectorconfidence descending and originalindex tie; any remaining pair overlap>0.1 ofsmaller rejects BOTH. Assign minor sharedpixels in the same order only after allpairrejections. Require a unique maskIoU>=.5 edge in both directions between frames. No known/unknown initial protection.",
            "confirmation": "All survivors are anonymous. No64px orborder gate removes objects; small/clipped views may be unsuitable for later human naming. No label-derived selection or threshold search.",
            "scope": "Two exposed first frames only, optimistic camera-trained detector. No Cutie propagation, name assignment, truth load, scoring, GPU, or footage3000+. Prior8humanselectedmasks are not an input. Keep all original/pretrim masks and every rejection. Review candidate masks before any biological label counts.",
        },
    )


def verify(protocol_path):
    value = json.loads(protocol_path.read_text())
    for path, expected in value["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen startup input changed:{path}")
    if (
        value["libraries"] != libraries()
        or value["opencv"] != cv2.__version__
        or value["rules"] != RULES
    ):
        raise ValueError("Frozen runtime or selection policy changed")
    return value


def infer_frames(protocol, output):
    import torch
    from ultralytics import SAM as SegmentAnything

    torch.set_num_threads(2)
    model = SegmentAnything(protocol["sam"])
    capture = cv2.VideoCapture(protocol["clip"])
    frames, trimmed = [], []
    try:
        for index, (source, proposals) in enumerate(
            zip(protocol["source_rows"], protocol["proposal_rows"], strict=True)
        ):
            ok, image = capture.read()
            if not ok or pixels_hash(image) != source["pixels_sha256"]:
                raise ValueError("Decoded first-frame source changed")
            boxes = proposals["boxes"]
            tick = time.perf_counter()
            result = model.predict(
                image,
                bboxes=[[b[k] for k in ("x1", "y1", "x2", "y2")] for b in boxes],
                verbose=False,
                **protocol["sam_settings"],
            )[0]
            masks = result.masks.data.cpu().numpy() > 0.5
            if masks.shape != (len(boxes), *image.shape[:2]):
                raise ValueError("SAM changed prompt order or source dimensions")
            parameter = next(model.predictor.model.parameters())
            if (
                str(parameter.device) != "cpu"
                or str(parameter.dtype) != "torch.float32"
            ):
                raise ValueError("Actual SAM must remain CPU FP32")
            decision, disjoint = select_masks(masks, boxes, protocol["rules"])
            mask_path, image_path = (
                output / f"{index}-masks.npz",
                output / f"{index}-source.png",
            )
            np.savez_compressed(mask_path, original=masks, disjoint=disjoint)
            if not cv2.imwrite(str(image_path), image):
                raise OSError("Cannot save exact source image")
            frames.append(
                {
                    "second": source["second"],
                    "source_pixels_sha256": source["pixels_sha256"],
                    "image": str(image_path),
                    "image_sha256": digest(image_path),
                    "masks": str(mask_path),
                    "masks_sha256": digest(mask_path),
                    "proposals": boxes,
                    "decision": decision,
                    "elapsed_seconds": time.perf_counter() - tick,
                    "actual_device": str(parameter.device),
                    "actual_dtype": str(parameter.dtype),
                }
            )
            trimmed.append(disjoint)
    finally:
        capture.release()
    return frames, trimmed


def run(protocol_path, output):
    protocol = verify(protocol_path)
    output.mkdir(parents=True, exist_ok=False)
    frames, trimmed = infer_frames(protocol, output)
    matches = temporal_matches(
        *trimmed,
        frames[0]["decision"]["selected"],
        frames[1]["decision"]["selected"],
        protocol["rules"]["temporal_mask_iou"],
    )
    write_json(
        output / "manifest.json",
        {
            "protocol_sha256": digest(protocol_path),
            "complete": True,
            "frames": frames,
            "temporal": matches,
            "status": "PENDING_MASK_REVIEW_NO_BIOLOGICAL_NAMES_OR_TRUTH_LOADED",
        },
    )
    print(
        json.dumps(
            {
                "frame_candidates": [len(r["proposals"]) for r in frames],
                "frame_survivors": [len(r["decision"]["selected"]) for r in frames],
                "temporally_confirmed_anonymous": len(matches["matched"]),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or (args.mode == "run" and args.protocol is None):
        parser.error("Use a fresh output and the fixed protocol for inference")
    freeze(args.output) if args.mode == "freeze" else run(args.protocol, args.output)
