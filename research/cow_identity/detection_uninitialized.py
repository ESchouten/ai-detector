"""Prepare or run the fixed six-seed uninitialized-unknown exposure control.

Unknown calves7/8 are already visible at the start. This is not a physical-entry
experiment and does not add objects dynamically. The original streaming runner
and all its inference/policy helpers remain unchanged.
"""

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_cutie import indexed_seed
from detection_streaming import checked_inputs, run

ROOT = Path(__file__).parent
BASE = ROOT / "detection_streaming_protocol.json"
PROTOCOL = ROOT / "detection_uninitialized_protocol.json"
SEEDS = Path(".cache/cow-cutie/uninitialized-seeds")
OUTPUT = Path(".cache/cow-cutie/uninitialized-unknown")
WINDOWS = [[330, 629], [930, 1229], [1230, 1529]]


def derive_masks(masks):
    if masks.ndim != 3 or masks.shape[0] != 8:
        raise ValueError("Expected the original eight reviewed binary masks")
    selected = masks[:6].copy()
    original, changed = indexed_seed(masks), indexed_seed(selected)
    if any(
        not np.array_equal(original == slot, changed == slot) for slot in range(1, 7)
    ):
        raise ValueError("Removing unknown seeds changed a named seed's pixels")
    if np.any((changed != original) & ~np.isin(original, (7, 8))):
        raise ValueError("Only anonymous seed pixels may become background")
    return selected


def prepare():
    if PROTOCOL.exists() or SEEDS.exists() or OUTPUT.exists():
        raise ValueError("Preserve the previous freeze, seeds and output")
    base = json.loads(BASE.read_text())
    if base["seeded_cows"] != list(range(1, 9)) or base["named_cows"] != list(
        range(1, 7)
    ):
        raise ValueError("Baseline seed/name assignment differs from this control")
    for path, expected in base["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen baseline input changed:{path}")
    original = Path(base["inputs"]["seed_masks"])
    original_manifest = Path(base["inputs"]["seed_manifest"])
    with np.load(original, allow_pickle=False) as arrays:
        masks = derive_masks(arrays["masks"])
    seeds = json.loads(original_manifest.read_text())["rows"][0]
    if seeds["frame"] != 1 or [p["cow"] for p in seeds["prompts"]] != list(range(1, 9)):
        raise ValueError("Original reviewed seed order changed")
    SEEDS.mkdir(parents=True)
    mask_path, manifest_path = SEEDS / "0-masks.npz", SEEDS / "manifest.json"
    np.savez_compressed(mask_path, masks=masks)
    write_json(
        manifest_path,
        {
            "scope": "Six unchanged reviewed named masks; original anonymous7/8masks omitted, no new prompts or truth lookups",
            "base_protocol_sha256": digest(BASE),
            "original_masks_sha256": digest(original),
            "original_manifest_sha256": digest(original_manifest),
            "rows": [
                {
                    **seeds,
                    "prompts": seeds["prompts"][:6],
                    "mask_file_sha256": digest(mask_path),
                }
            ],
            "initialization": {
                "kept_original_slots": list(range(1, 7)),
                "omitted_slots": [7, 8],
                "named_pixels_unchanged": True,
                "areas": [int(mask.sum()) for mask in masks],
            },
        },
    )
    protocol = copy.deepcopy(base)
    protocol.update(
        frozen_at_utc=datetime.now(UTC).isoformat(),
        scope="Fixed six-seed exposure to unknown uninitialized animals already visible at t0. Not physical arrival, appearance re-identification or dynamic addition. No GPU execution authorized by preparing this protocol.",
        seeded_cows=list(range(1, 7)),
        anonymous_cows=[],
        uninitialized_unknown_cows=[7, 8],
        base_protocol_sha256=digest(BASE),
        experiment={
            "only_algorithm_change": "Omit initial anonymous7/8masks; keep named1..6pixels and complete selected online policy unchanged",
            "truth_domain": list(range(1, 9)),
            "quarantine_domain": list(range(1, 7)),
            "dynamic_addition": False,
            "deletion": False,
            "model_or_threshold_selection": False,
        },
        limitations=[
            "Unknown7/8are present initially, so this evaluates uninitialized-unknown exclusion, not physical entry.",
            "Cutie must be rerun from t0; deleting7/8from old outputs is not equivalent.",
            "All three panels are exposed development. All8truth animals and original known/unknown denominators remain; missing predictions count.",
            "No source pixels beyond1529s; no reserved input files. GPU scheduling still controlled by parent.",
        ],
    )
    protocol["inputs"].update(
        seed_masks=str(mask_path), seed_manifest=str(manifest_path)
    )
    for path in (
        BASE,
        original,
        original_manifest,
        mask_path,
        manifest_path,
        Path(__file__),
        ROOT / "cutie_object_state.py",
        ROOT / "test_detection_uninitialized.py",
        ROOT / "detection_uninitialized_score.py",
    ):
        protocol["files"][str(path)] = digest(path)
    write_json(PROTOCOL, protocol)
    print(
        json.dumps(
            {
                "protocol_sha256": digest(PROTOCOL),
                "named_mask_areas": [int(m.sum()) for m in masks],
                "files": len(protocol["files"]),
            }
        )
    )


def run_control(args):
    protocol, clip, masks, seeds, libraries = checked_inputs(args)
    if (
        protocol["seeded_cows"] != list(range(1, 7))
        or protocol["named_cows"] != list(range(1, 7))
        or protocol["uninitialized_unknown_cows"] != [7, 8]
        or protocol["anonymous_cows"]
    ):
        raise ValueError("This runner requires six fixed contiguous named slots")
    if (
        protocol["comparison_windows"] != WINDOWS
        or protocol["last_processed_second"] != 1529
    ):
        raise ValueError("This control may only process the exposed0..1529sequence")
    if protocol["experiment"]["dynamic_addition"] or protocol["experiment"]["deletion"]:
        raise ValueError("Dynamic objects require a separate stable-ID-aware runner")
    run(args, protocol, clip, masks, seeds, libraries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--frames", type=int)
    args = parser.parse_args()
    prepare() if args.action == "prepare" else run_control(args)
