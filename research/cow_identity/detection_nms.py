"""Explore stricter SDK-style NMS using existing calibration predictions only."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_assessment import PROTOCOL, boxes_above, load_panel, score
from video_assessment import pair_boxes


def suppress(predictions, threshold):
    import torch
    from torchvision.ops import nms

    result = []
    for row in predictions:
        boxes = torch.tensor(row["boxes"], dtype=torch.float32).reshape(-1, 4)
        scores = torch.tensor(row["confidence"], dtype=torch.float32)
        indices = nms(boxes, scores, threshold).tolist()
        result.append(
            {
                **row,
                "boxes": [row["boxes"][index] for index in indices],
                "confidence": [row["confidence"][index] for index in indices],
            }
        )
    return result


def changed_matches(frames, original, filtered, confidence):
    lost, recovered = 0, 0
    for frame, before, after in zip(frames, original, filtered, strict=True):
        truth = frame["truth"]
        baseline = set(pair_boxes(boxes_above(before, confidence), truth).values())
        selected = set(pair_boxes(boxes_above(after, confidence), truth).values())
        lost += len(baseline - selected)
        recovered += len(selected - baseline)
    return {"newly_missed_annotations": lost, "newly_matched_annotations": recovered}


def main():
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "video", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    args = parser.parse_args()
    source = json.loads(args.report.read_text())
    if source["split"] != "calibration":
        parser.error("NMS selection is restricted to the calibration split")
    if source["protocol_sha256"] != digest(args.protocol):
        parser.error("Source predictions must use the selected protocol")
    args.split = "calibration"
    protocol = json.loads(args.protocol.read_text())
    frames = load_panel(args, protocol)
    inference = source["inference"]
    if [frame["sha256"] for frame in frames] != inference["provenance"]["images"]:
        parser.error("Source prediction pixels do not match the calibration images")
    baseline_iou = inference["provenance"]["iou"]
    thresholds = (0.45, 0.60, baseline_iou)
    if any(threshold > baseline_iou for threshold in thresholds):
        parser.error("Cached NMS cannot restore previously suppressed predictions")
    torch.set_num_threads(2)
    predictions = inference["predictions"]
    results = []
    for threshold in thresholds:
        filtered = (
            predictions
            if threshold == baseline_iou
            else suppress(predictions, threshold)
        )
        results.extend(
            {
                "nms_iou": threshold,
                **score(frames, filtered, confidence),
                **changed_matches(frames, predictions, filtered, confidence),
            }
            for confidence in protocol["selection"]["thresholds"]
        )
    report = {
        "scope": "Exploratory calibration-only NMS control; no final-window inference",
        "caveat": "Cached boxes are image-clipped. Stricter original SDK NMS may differ at borders; any promotion needs fresh SDK inference. Baseline predictions are reused unchanged.",
        "source_report_sha256": digest(args.report),
        "baseline_iou": baseline_iou,
        "iou_candidates": thresholds,
        "metrics": results,
        "choice": max(
            results,
            key=lambda row: (row["f1"], row["precision"], row["confidence"]),
        ),
    }
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
