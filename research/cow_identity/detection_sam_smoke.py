"""Bounded 512-pixel resource controls; no tracking-accuracy claims."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmark import digest, write_json
from detection_sam_tracking import (
    PROTOCOL,
    masked_boxes,
    predictor_for,
    reclaim_mps_cache,
)
from video_assessment import annotations, detector_libraries, pixels_hash, truth_at


def main():
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "cache", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--frames", type=int, choices=(3, 20), default=3)
    parser.add_argument("--reclaim-cache", action="store_true")
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text())
    if digest(args.model) != protocol["model_sha256"]:
        parser.error("Unexpected SAM model")
    if digest(args.source_pickle) != protocol["source_annotations_sha256"]:
        parser.error("Unexpected publisher annotation source")
    manifest = json.loads((args.cache / "sampled.json").read_text())
    clip = args.cache / "sampled.avi"
    if digest(clip) != manifest["clip_sha256"] or manifest["contract"][
        "protocol_sha256"
    ] != digest(PROTOCOL):
        parser.error("Sampled clip does not match the frozen source protocol")
    records, _ = annotations(args)
    seeds = sorted(
        truth_at(records, 1, manifest["width"], manifest["height"]),
        key=lambda row: row["cow"],
    )
    if [row["cow"] for row in seeds] != protocol["seeded_cows"]:
        parser.error("The seed frame must contain the frozen eight objects")
    torch.set_num_threads(2)
    predictor = predictor_for(args.model, "mps", {**protocol, "imgsz": 512})
    outputs = predictor(
        source=str(clip), bboxes=[row["box"] for row in seeds], stream=True
    )
    contract = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "scope": "Initial-frame resource diagnostic, not an accuracy evaluation",
        "imgsz": 512,
        "frames": args.frames,
        "reclaim_after_bytes": 6 * 1024**3 if args.reclaim_cache else None,
        "processing_fps": 2,
        "objects": 8,
        "precision": "FP32",
        "device": "mps",
        "library_versions": detector_libraries(),
        "source_protocol_sha256": digest(PROTOCOL),
        "clip_sha256": manifest["clip_sha256"],
        "model_sha256": digest(args.model),
        "runner_sha256": digest(Path(__file__)),
        "adapter_sha256": digest(PROTOCOL.with_name("detection_sam_tracking.py")),
        "annotations_sha256": digest(args.annotations),
    }
    write_json(args.output.with_suffix(".protocol.json"), contract)
    rows = []
    try:
        for index in range(args.frames):
            started = time.perf_counter()
            result = next(outputs)
            torch.mps.synchronize()
            memory, reclamation = reclaim_mps_cache(
                predictor, "mps", contract["reclaim_after_bytes"]
            )
            if pixels_hash(result.orig_img) != manifest["rows"][index]["pixels_sha256"]:
                raise ValueError("SDK source pixels or timing changed")
            row = {
                "frame": index,
                "second": index / 2,
                "elapsed_seconds": time.perf_counter() - started,
                "visible_object_slots": predictor.visible_objects,
                "boxes": masked_boxes(result, predictor.visible_objects),
                "reclamation": reclamation,
                **memory,
            }
            rows.append(row)
            print(
                json.dumps(
                    {key: value for key, value in row.items() if key != "boxes"}
                ),
                flush=True,
            )
            if memory["mps_driver_bytes"] > 8 * 1024**3:
                break
    finally:
        outputs.close()
    write_json(args.output, {"contract": contract, "frames": rows})


if __name__ == "__main__":
    main()
