"""Explain every saved birth rejection from fixed masks; no new inference."""

import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_birth_run import PROTOCOL, checked_inputs

ROOT = Path(__file__).parent
DIRECTORY = Path(".cache/cow-cutie/crowded-births")


def rejection_reasons(mask, masks, attempt, inside, overlap, rules):
    reasons = []
    if not mask.any() or inside < rules["minimum_prompt_support"]:
        reasons.append("insufficient_prompt_containment")
    if any(
        np.any(mask & other)
        for j, other in enumerate(masks)
        if j != attempt["mask_index"]
    ):
        reasons.append("overlapping_new_masks")
    if any(fraction > rules["maximum_mask_overlap"] for fraction in overlap.values()):
        reasons.append("existing_foreground_overlap")
    return reasons


def execute():
    protocol, _, _, _ = checked_inputs(PROTOCOL)
    path = DIRECTORY / "streaming.json"
    value = json.loads(path.read_text())
    if not value["complete"] or value["provenance"]["protocol_sha256"] != digest(
        PROTOCOL
    ):
        raise ValueError("Complete frozen crowded control required")
    rules, results, counts = protocol["births"], [], Counter()
    for previous, frame in zip(
        value["all_frames"][:-1], value["all_frames"][1:], strict=True
    ):
        if not frame["sam_attempts"]:
            continue
        old_path = DIRECTORY / "masks" / f"{previous['second']:g}.png"
        if digest(old_path) != previous["mask_sha256"]:
            raise ValueError("Previous active mask changed")
        old = cv2.imread(str(old_path), cv2.IMREAD_UNCHANGED)
        for attempt in frame["sam_attempts"]:
            cache = Path(attempt["cache"])
            if digest(cache) != attempt["cache_sha256"]:
                raise ValueError("Saved SAM attempt changed")
            with np.load(cache, allow_pickle=False) as archive:
                masks = archive["masks"]
            mask, box = masks[attempt["mask_index"]], attempt["box"]
            area = int(mask.sum())
            inside = (
                int(mask[box["y1"] : box["y2"], box["x1"] : box["x2"]].sum()) / area
                if area
                else 0
            )
            overlap = {
                int(i): float(
                    np.count_nonzero(mask & (old == i))
                    / min(area, np.count_nonzero(old == i))
                )
                for i in np.unique(old)
                if i and area
            }
            reasons = rejection_reasons(mask, masks, attempt, inside, overlap, rules)
            if attempt["accepted"] != (not reasons):
                raise ValueError(
                    "Reconstructed fixed rejection differs from recorded decision"
                )
            counts.update(reasons or ["accepted"])
            results.append(
                {
                    "second": frame["second"],
                    "proposal_index": attempt["proposal_index"],
                    "box": box,
                    "accepted": attempt["accepted"],
                    "reasons": reasons,
                    "prompt_containment": inside,
                    "overlap_by_old_slot": overlap,
                }
            )
    write_json(
        ROOT / "results/2026-10-03/detection/birth-attempt-audit.json",
        {
            "scope": "Posthoc rejection diagnosis only, unchanged fixed decisions; no truth or model inference",
            "sources": {str(p): digest(p) for p in (PROTOCOL, path, Path(__file__))},
            "counts": dict(counts),
            "attempts": results,
        },
    )
    print(
        json.dumps(
            {
                "counts": dict(counts),
                "first_rejected": next((r for r in results if not r["accepted"]), None),
            }
        )
    )


if __name__ == "__main__":
    cv2.setNumThreads(2)
    execute()
