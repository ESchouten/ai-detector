"""All original truth and windows for the exposed crowded birth control."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_birth_run import checked_inputs
from detection_cutie import boxes_from_mask
from detection_cutie_variants import largest_components
from detection_reserved_score import acceptance, pooled_naming, runtime_summary
from detection_sam_tracking import score
from detection_streaming_assessment import THRESHOLDS
from detection_uninitialized import WINDOWS
from video_assessment import annotations


def verify_frame(frame, source, index, directory, live):
    if (
        frame["upstream_step"] != index
        or frame["publisher_frame"] != source["publisher_frame"]
        or frame["source_pixels_sha256"] != source["pixels_sha256"]
        or frame["second"] != source["second"]
    ):
        raise ValueError("Recorded dynamic source/counter differs")
    new = frame["born_ids"]
    if new != list(range(max(live) + 1, max(live) + len(new) + 1)):
        raise ValueError("Anonymous birth IDs cannot reuse old slots")
    live.update(new)
    if max(live) > 8 or {int(i) for i in frame["object_to_channel"]} != live:
        raise ValueError("Original object limit or live registry changed")
    if not set(frame["named_track_ids"]).issubset(
        set(range(6)) & {b["track_id"] for b in frame["boxes"]}
    ):
        raise ValueError("A new anonymous object cannot receive a name")
    path = directory / "masks" / f"{frame['second']:g}.png"
    if digest(path) != frame["mask_sha256"]:
        raise ValueError("Output mask changed")
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if not set(np.unique(mask)).issubset({0, *live}):
        raise ValueError("Mask contains undeclared objects")
    keys = ("track_id", "x1", "y1", "x2", "y2")
    expected = boxes_from_mask(largest_components(mask)[0])
    if [[b[k] for k in keys] for b in expected] != [
        [b[k] for k in keys] for b in frame["boxes"]
    ]:
        raise ValueError("Mask and published geometry disagree")


def validate(value, clip, directory):
    if len(value["all_frames"]) != 3059 or len(value["timeline"]) != 1530:
        raise ValueError("Keep every processed and scored exposed timestamp")
    live = set(range(1, 7))
    for index, (frame, source) in enumerate(
        zip(value["all_frames"], clip["rows"], strict=True)
    ):
        verify_frame(frame, source, index, directory, live)
    integers = [r for r in value["all_frames"] if float(r["second"]).is_integer()]
    if integers != value["timeline"]:
        raise ValueError("Scored rows must equal actual recorded integer decisions")


def execute(args):
    protocol, clip, seeds, cached = checked_inputs(args.protocol)
    value = json.loads(args.streaming.read_text())
    if (
        value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or value["provenance"]["libraries"] != protocol["libraries"]
    ):
        raise ValueError("Different dynamic execution provenance")
    bindings = {
        str(p): digest(p) for p in (args.protocol, args.streaming, Path(__file__))
    }
    if not value["complete"]:
        write_json(
            args.output,
            {
                "status": "FAILED_INCOMPLETE_CONTROL",
                "stop_reason": value["stop_reason"],
                "processed_frames": len(value["all_frames"]),
                "expected_frames": 3059,
                "sources": bindings,
                "scores": None,
            },
        )
        return
    validate(value, clip, args.streaming.parent)
    for p in (args.annotations, args.source_pickle):
        if digest(p) != protocol["files"][str(p)]:
            raise ValueError("Original eight-animal truth changed")
    records, _ = annotations(args)
    # None is an anonymous bookkeeping label, never an inferred publisher ID.
    scoring_slots = [*seeds["prompts"], {"cow": None}, {"cow": None}]
    windows = {
        str(window[0]): score(
            value,
            records,
            clip,
            {**protocol, "score_seconds": window},
            scoring_slots,
            name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
        )
        for window in WINDOWS
    }
    batches = {
        a["cache"]: a["batch_seconds"]
        for r in value["all_frames"]
        for a in r["sam_attempts"]
    }
    report = {
        "status": "COMPLETE_EXPOSED_CONTROL",
        "sources": bindings,
        "conditions": windows,
        "pooled": pooled_naming(windows),
        "acceptance": {k: acceptance(v, THRESHOLDS) for k, v in windows.items()},
        "births": [
            {"second": r["second"], "stable_id": i, "name": None}
            for r in value["all_frames"]
            for i in r["born_ids"]
        ],
        "sam_batches": len(batches),
        "sam_batch_seconds": sum(batches.values()),
        "sam_prompt_count": sum(len(r["sam_attempts"]) for r in value["all_frames"]),
        "runtime_cached_propagation_plus_sam": runtime_summary(value, 2),
        "missing_half_second_detector_fill": {
            "elapsed_seconds": cached["elapsed_seconds"],
            "model_seconds": sum(cached["new_inference_seconds"]),
            "new_calls": len(cached["new_inference_seconds"]),
        },
        "limitation": "Exposed crowded development, cached detector evidence and anonymous births only. Logical no-birth parity verified separately; not joint live latency, biological re-identification, deletion/endurance or held-out farm evidence.",
    }
    write_json(args.output, report)
    print(json.dumps({k: report[k] for k in ("acceptance", "pooled", "births")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "streaming", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    execute(parser.parse_args())
