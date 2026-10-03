"""Inventory frozen first-frame candidates; never infer or select new masks."""

import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_birth_run import PROTOCOL, checked_inputs
from detection_box_consensus import correspondences
from passage_entry_births import birth_candidates, intersection_over_smaller

ROOT = Path(__file__).parent


def execute():
    protocol, clip, _, cached = checked_inputs(PROTOCOL)
    seed_path = Path(".cache/cow-cutie/actual-seed-masks/manifest.json")
    mask_path = seed_path.parent / "0-masks.npz"
    seed = json.loads(seed_path.read_text())
    initial_path = (
        ROOT / "results/2026-10-03/detection/cutie-actual-initialization.json"
    )
    initial = json.loads(initial_path.read_text())
    if (
        digest(initial_path) != seed["protocol"]["proposal_report_sha256"]
        or digest(mask_path) != seed["mask_file_sha256"]
    ):
        raise ValueError("Original reviewed initialization changed")
    prompts = seed["rows"][0]["prompts"]
    boxes = cached["timeline"][0]["boxes"]
    source = clip["rows"][0]["pixels_sha256"]
    if (
        seed["rows"][0]["source_pixels_sha256"] != source
        or initial["inference"]["provenance"]["pixels_sha256"] != source
    ):
        raise ValueError("The two precision modes must use the same source frame")
    prompt_boxes = [
        dict(zip(("x1", "y1", "x2", "y2"), p["box"], strict=True)) for p in prompts
    ]
    _, reciprocal = correspondences(prompt_boxes, boxes, 0.5)
    if len(reciprocal) != 8:
        raise ValueError("Every reviewed seed must have a current raw counterpart")
    _, pending = birth_candidates(boxes, [], [], protocol["births"])
    overlaps = [
        {
            "proposals": [i, j],
            "intersection_over_smaller": intersection_over_smaller(a, b),
        }
        for i, a in enumerate(boxes)
        for j, b in enumerate(boxes)
        if i < j
        and intersection_over_smaller(a, b) >= protocol["births"]["duplicate_overlap"]
    ]
    with np.load(mask_path, allow_pickle=False) as archive:
        masks = archive["masks"]
    report = {
        "scope": "CPU inventory of existing frame-zero evidence only, not a new automatic initialization experiment or farmer-effort measurement",
        "source_pixels_sha256": source,
        "sources": {
            str(p): digest(p)
            for p in (
                PROTOCOL,
                initial_path,
                seed_path,
                mask_path,
                Path(__file__),
                Path(protocol["inputs"]["proposals"]),
            )
        },
        "historical_cpu_fp32_proposal_count": len(initial["inference"]["boxes"]),
        "current_mps_fp16_proposals": boxes,
        "reviewed_selections": seed["protocol"]["confirmed"],
        "review_rejected_duplicates": seed["protocol"]["rejected_proposals"],
        "reviewed_to_current_reciprocal_proposals": reciprocal,
        "current_box_conflicts_at_existing_birth_duplicate_threshold": overlaps,
        "empty_scene_birth_rule_pending_proposals": [boxes.index(p) for p in pending],
        "existing_reviewed_masks": {
            "count": len(masks),
            "areas": masks.sum(axis=(1, 2)).tolist(),
            "overlap_pixels": int(np.count_nonzero(masks.sum(axis=0) > 1)),
        },
        "assessment": [
            "Eight actual reviewed masks already support an all-anonymous startup followed by six explicit human confirmations in principle; labels need not control object initialization.",
            "This is not fully automatic: twelve raw proposals contain duplicate body boxes, and the existing conservative birth rule also suppresses the real adjacent foreground animals at proposals0/4. Only four proposals survive that rule in an empty scene.",
            "Do not seed all twelve or silently use the expected animal count. A reviewed single-animal mask list and explicit duplicate rejection remain necessary unless a separate automatic initializer is validated.",
            "All eight reviewed masks are disjoint, but no SAM results for rejected duplicate proposals exist here. This inventory cannot prove an automatic mask-overlap deduplicator works.",
            "Original reviewed prompts came from CPU FP32; current online corroboration is MPS FP16 and has slightly different coordinates. Reusing the old masks does not prove a fresh online initializer reproduces them.",
            "Frame zero was included in detector training. The eight-slot run uses one simultaneous insertion cohort; the dynamic run inserts six plus one at5s and one at24s, creating three cohorts. Timing, mask content and SDK cross-cohort competition are confounded until a controlled follow-up.",
        ],
    }
    write_json(
        ROOT / "results/2026-10-03/detection/startup-proposal-audit.json", report
    )
    print(
        json.dumps(
            {
                "current_proposals": len(boxes),
                "birth_rule_pending": report[
                    "empty_scene_birth_rule_pending_proposals"
                ],
                "overlap_pixels": report["existing_reviewed_masks"]["overlap_pixels"],
            }
        )
    )


if __name__ == "__main__":
    execute()
