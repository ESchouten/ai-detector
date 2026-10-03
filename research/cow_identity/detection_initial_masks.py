"""Make independently retained CPU SAM seeds from reviewed actual detector boxes."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_cutie import indexed_seed
from video_assessment import detector_libraries, pixels_hash, read_frame


def agreement(first, second):
    intersection = int(np.count_nonzero(first & second))
    union = int(np.count_nonzero(first | second))
    return intersection / union if union else 1.0


def compare_masks(actual, original):
    actual_indexed, original_indexed = indexed_seed(actual), indexed_seed(original)
    rows = []
    for index, (new, old) in enumerate(zip(actual, original, strict=True)):
        object_id = index + 1
        rows.append(
            {
                "original_slot_id": object_id,
                "actual_area": int(new.sum()),
                "comparison_area": int(old.sum()),
                "binary_mask_agreement_iou": agreement(new, old),
                "actual_indexed_area": int((actual_indexed == object_id).sum()),
                "comparison_indexed_area": int((original_indexed == object_id).sum()),
                "indexed_mask_agreement_iou": agreement(
                    actual_indexed == object_id, original_indexed == object_id
                ),
            }
        )
    return {
        "objects": rows,
        "actual_overlap_pixels": int(np.count_nonzero(actual.sum(0) > 1)),
        "comparison_overlap_pixels": int(np.count_nonzero(original.sum(0) > 1)),
        "actual_present_indexed_ids": sorted(
            set(map(int, np.unique(actual_indexed))) - {0}
        ),
        "indexed_pixels_changed": int(
            np.count_nonzero(actual_indexed != original_indexed)
        ),
    }


def montage(image, actual, original, path):
    tiles = []
    for index, (new, old) in enumerate(zip(actual, original, strict=True)):
        ys, xs = np.nonzero(new | old)
        crop = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        panels = [
            cv2.resize(np.where(mask[..., None], image, 127)[crop], (240, 180))
            for mask in (old, new)
        ]
        tile = cv2.hconcat(panels)
        for x, label in ((3, "Original"), (243, "Actual proposal")):
            cv2.putText(
                tile,
                f"Slot{index + 1}: {label}",
                (x, 17),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (0, 255, 255),
                1,
            )
        tiles.append(tile)
    sheet = cv2.vconcat([cv2.hconcat(tiles[i : i + 2]) for i in range(0, 8, 2)])
    if not cv2.imwrite(str(path), sheet):
        raise ValueError("Could not save initialization contact sheet")


def run_sam(image, args, protocol):
    import torch
    from ultralytics import SAM

    torch.set_num_threads(2)
    proposals = json.loads(args.proposals.read_text())["inference"]["boxes"]
    prompts = [
        {"cow": row["cow"], "box": proposals[row["proposal"]]}
        for row in protocol["confirmed"]
    ]
    started = time.perf_counter()
    model = SAM(str(args.model))
    result = model.predict(
        image,
        bboxes=[row["box"] for row in prompts],
        verbose=False,
        **protocol["settings"],
    )[0]
    masks = result.masks.data.cpu().numpy() > 0.5
    if masks.shape != (8, *image.shape[:2]):
        raise ValueError("SAM did not preserve the eight original prompt slots")
    parameter = next(model.predictor.model.parameters())
    return (
        masks,
        prompts,
        {
            "elapsed_seconds": time.perf_counter() - started,
            "actual_device": str(parameter.device),
            "actual_dtype": str(parameter.dtype),
            "libraries": detector_libraries(),
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("proposals", "model", "video", "original-masks", "output", "report"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    path = Path(__file__).with_name("detection_initial_masks_protocol.json")
    protocol = json.loads(path.read_text())
    for name, key in (
        ("proposals", "proposal_report_sha256"),
        ("model", "sam_sha256"),
        ("video", "video_sha256"),
        ("original_masks", "original_masks_sha256"),
    ):
        if digest(getattr(args, name)) != protocol[key]:
            parser.error(f"Changed frozen source {name}")
    if args.output.exists():
        parser.error("Preserve previous masks; select a fresh output directory")
    capture = cv2.VideoCapture(str(args.video))
    try:
        _, image = read_frame(capture, 0, capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    expected = json.loads(args.proposals.read_text())["inference"]["provenance"]
    if pixels_hash(image) != expected["pixels_sha256"]:
        parser.error("First-frame source pixels differ from reviewed proposals")
    masks, prompts, inference = run_sam(image, args, protocol)
    args.output.mkdir(parents=True)
    mask_path = args.output / "0-masks.npz"
    np.savez_compressed(mask_path, masks=masks)
    with np.load(args.original_masks, allow_pickle=False) as archive:
        original = archive["masks"]
    contact = args.output / "mask-comparison.jpg"
    montage(image, masks, original, contact)
    report = {
        "protocol": protocol,
        "protocol_sha256": digest(path),
        "runner_sha256": digest(Path(__file__)),
        "inference": inference,
        "mask_file_sha256": digest(mask_path),
        "contact_sha256": digest(contact),
        "comparison": compare_masks(masks, original),
        "rows": [
            {
                "frame": 1,
                "second": 0,
                "source_pixels_sha256": pixels_hash(image),
                "prompts": prompts,
                "mask_file_sha256": digest(mask_path),
            }
        ],
    }
    write_json(args.output / "manifest.json", report)
    write_json(args.report, report)
    print(json.dumps(report["comparison"]))


if __name__ == "__main__":
    main()
