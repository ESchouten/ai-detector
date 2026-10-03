"""One frozen containment diagnostic on existing anonymous startup masks only."""

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_startup_masks import (
    RULES,
    remaining_ambiguity,
    select_masks,
    temporal_matches,
)

ROOT = Path(__file__).parent
BASE = Path(".cache/cow-startup-mask-control/manifest.json")
RESULTS = ROOT / "results/2026-10-03/detection"
CONTAINMENT = 0.9


def relations(masks, kept, rows, minimum):
    return {
        parent: [
            child
            for child in kept
            if rows[parent]["area"] > rows[child]["area"]
            and np.count_nonzero(masks[parent] & masks[child]) / rows[child]["area"]
            >= minimum
        ]
        for parent in kept
    }


def guarded_groups(masks, contains, rows, maximum_overlap):
    """A parent containing separate parts might contain two animals: abstain."""
    groups = []
    for parent, children in contains.items():
        separate = [
            [left, right]
            for index, left in enumerate(children)
            for right in children[index + 1 :]
            if np.count_nonzero(masks[left] & masks[right])
            / min(rows[left]["area"], rows[right]["area"])
            <= maximum_overlap
        ]
        if separate:
            groups.append(
                {"parent": parent, "children": children, "separate_pairs": separate}
            )
    return groups


def containment_selection(masks, proposals):
    original, _ = select_masks(masks, proposals, RULES)
    rows = copy.deepcopy(original["rows"])
    # Reuse the exact support and IoU-NMS stages. Only defer their later
    # overlap rejection/pixel assignment until the new containment stage.
    for row in rows:
        row.pop("assigned_area", None)
        row["rejections"] = [
            reason for reason in row["rejections"] if reason != "ambiguous_overlap"
        ]
    kept = [i for i in original["confidence_order"] if not rows[i]["rejections"]]
    contains = relations(masks, kept, rows, CONTAINMENT)
    guards = guarded_groups(masks, contains, rows, RULES["maximum_remaining_overlap"])
    blocked = {i for group in guards for i in [group["parent"], *group["children"]]}
    for i in blocked:
        rows[i]["rejections"].append("multi_part_parent_ambiguity")
    ordered = sorted(
        kept, key=lambda i: (-rows[i]["area"], -proposals[i]["confidence"], i)
    )
    for parent in ordered:
        if rows[parent]["rejections"]:
            continue
        for child in contains[parent]:
            if not rows[child]["rejections"]:
                rows[child]["rejections"].append("contained_fragment")
                rows[child]["suppressed_by"] = parent
    residual = [i for i in kept if "contained_fragment" not in rows[i]["rejections"]]
    ambiguous = remaining_ambiguity(
        masks, residual, rows, RULES["maximum_remaining_overlap"]
    )
    for i in {k for pair in ambiguous for k in (pair["left"], pair["right"])}:
        rows[i]["rejections"].append("ambiguous_overlap")
    selected = [i for i in kept if not rows[i]["rejections"]]
    disjoint, occupied = np.zeros_like(masks), np.zeros(masks.shape[1:], bool)
    for i in selected:
        disjoint[i] = masks[i] & ~occupied
        occupied |= disjoint[i]
        rows[i]["assigned_area"] = int(disjoint[i].sum())
    return {
        "rows": rows,
        "selected": selected,
        "confidence_order": original["confidence_order"],
        "contains": contains,
        "guarded_groups": guards,
        "ambiguous_pairs": ambiguous,
    }, disjoint


def freeze(output):
    baseline = json.loads(BASE.read_text())
    files = [
        Path(__file__),
        ROOT / "test_detection_startup_containment.py",
        ROOT / "detection_startup_masks.py",
        ROOT / "test_detection_startup_masks.py",
        ROOT / "detection_startup_masks_protocol.json",
        ROOT / "benchmark.py",
        BASE,
        RESULTS / "startup-mask-review-cattle.json",
        RESULTS / "startup-mask-review-audit.json",
    ]
    files.extend(Path(frame["masks"]) for frame in baseline["frames"])
    write_json(
        output,
        {
            "status": "FROZEN_CACHED_MASK_CONTROL_BEFORE_OUTCOME",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "files": {str(p): digest(p) for p in files},
            "baseline": str(BASE),
            "minimum_containment": CONTAINMENT,
            "unchanged_rules": RULES,
            "algorithm": [
                "Replay original support.9 and maskIoU.8confidence/indexNMS exactly.",
                "For each surviving candidate, record strict-larger-area parents containing>=.9of its pixels. Compute all relations before removing candidates.",
                "If a parent contains two children whose intersection/minarea<=.1, mark parent and ALL its contained children ambiguous. Head+torso can also abstain; no semantic exception.",
                "Among unguarded candidates process largestarea first, then detectorconfidence/index; suppress contained unsuppressed fragments only when their parent itself is unblocked/unsuppressed.",
                "Apply original remaining-overlap>.1 rejection to BOTH endpoints, including guarded candidates, excluding suppressed fragments.",
                "Assign small residual shared pixels in originalconfidence/indexorder. Unchanged unique temporalIoU.5links on the resulting masks. No biological name supplied.",
            ],
            "scope": "Both original frames0/0.5 and all20candidates; no new SAM/GPU/source decode, no truths or threshold sweep. Compare exact original decision/disjoint-mask parity before accepting report. Use frozen geometry reviews only for subsequent descriptive interpretation; do not change temporal.495failure or infer independent generalization.",
        },
    )


def checked(protocol_path):
    value = json.loads(protocol_path.read_text())
    for path, expected in value["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen containment input changed:{path}")
    if value["minimum_containment"] != CONTAINMENT or value["unchanged_rules"] != RULES:
        raise ValueError("Containment rules changed")
    return value


def run(protocol_path, output):
    protocol = checked(protocol_path)
    baseline = json.loads(Path(protocol["baseline"]).read_text())
    frames, disjoint = [], []
    for frame in baseline["frames"]:
        with np.load(frame["masks"], allow_pickle=False) as archive:
            masks, recorded = archive["original"], archive["disjoint"]
        original, replayed = select_masks(masks, frame["proposals"], RULES)
        if original != frame["decision"] or not np.array_equal(recorded, replayed):
            raise ValueError(
                "Original decision and pixel assignment must match exactly"
            )
        decision, pixels = containment_selection(masks, frame["proposals"])
        frames.append(
            {
                "second": frame["second"],
                "source_mask_sha256": frame["masks_sha256"],
                "original_decision": original,
                "containment_decision": decision,
            }
        )
        disjoint.append(pixels)
    temporal = temporal_matches(
        *disjoint,
        frames[0]["containment_decision"]["selected"],
        frames[1]["containment_decision"]["selected"],
        RULES["temporal_mask_iou"],
    )
    write_json(
        output,
        {
            "protocol_sha256": digest(protocol_path),
            "baseline_parity": True,
            "frames": frames,
            "original_temporal": baseline["temporal"],
            "containment_temporal": temporal,
            "summary": {
                "raw_candidates": [len(f["proposals"]) for f in baseline["frames"]],
                "original_survivors": [
                    len(f["decision"]["selected"]) for f in baseline["frames"]
                ],
                "containment_survivors": [
                    len(f["containment_decision"]["selected"]) for f in frames
                ],
                "original_temporal_confirmed": len(baseline["temporal"]["matched"]),
                "containment_temporal_confirmed": len(temporal["matched"]),
            },
            "limits": protocol["scope"],
        },
    )
    print(json.dumps(json.loads(output.read_text())["summary"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or (args.mode == "run" and args.protocol is None):
        parser.error("Preserve frozen outputs and pass a protocol for execution")
    freeze(args.output) if args.mode == "freeze" else run(args.protocol, args.output)
