"""Audit frozen anonymous evidence without changing its label-blind selection.

This is an exposed-video geometry audit, not biological identity inference or
ear-number accuracy. All observations in a quality episode are assessed, not
just its saved photos. A common segmentation slot never supplies a truth label.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from anonymous_profile_inventory import qualified
from benchmark import digest, write_json
from video_assessment import pair_boxes, truth_at

from aidetector.domain.models import BoundingBox

ROOT = Path(__file__).parent
INVENTORY = ROOT / "results/2026-10-03/recognition/anonymous-profile-inventory.json"
INVENTORY_PROTOCOL = ROOT / "anonymous_profile_inventory_protocol.json"
RUN = Path(".cache/cow-startup-extended/streaming.json")
CLIP = Path(".cache/cow-cutie/reserved-2fps-clip/sampled.json")
ANNOTATIONS = Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz")


def evidence_summary(rows):
    """Count errors without treating unpaired boxes as a correct animal."""
    counts = Counter(str(row["cow"]) for row in rows if row["cow"] is not None)
    matched = sum(counts.values())
    dominant = max(counts.values(), default=0)
    return {
        "observations": len(rows),
        "matched": matched,
        "unmatched": len(rows) - matched,
        "animals": dict(counts),
        "distinct_matched_animals": len(counts),
        "mixed_animals": len(counts) > 1,
        "dominant_matched_fraction": dominant / matched if matched else None,
        "dominant_fraction_including_unmatched": dominant / len(rows) if rows else None,
        "fully_matched_single_animal": bool(rows)
        and len(counts) == 1
        and matched == len(rows),
    }


def summarize(inventory, matches):
    """The matches map contains every qualified (second, recorded-slot) pair."""
    episodes = []
    profiles = defaultdict(list)
    covered = set()
    for episode in inventory["episodes"]:
        keys = [
            (second, episode["recorded_slot"])
            for second in range(episode["first_second"], episode["last_second"] + 1)
        ]
        if len(keys) != episode["qualified_observations"] or covered.intersection(keys):
            raise ValueError(
                "Episode boundaries overlap or do not describe every sample"
            )
        covered.update(keys)
        rows = [matches[key] for key in keys]
        profiles[episode["profile_id"]].extend(rows)
        episodes.append({**episode, **evidence_summary(rows)})
    if covered != matches.keys():
        raise ValueError("Every qualified observation must belong to one episode")

    by_episode = {row["episode_id"]: row for row in episodes}
    candidates = {}
    for key in ("candidate_observations", "retained_candidates"):
        rows = []
        for candidate in inventory[key]:
            match = matches[candidate["second"], candidate["recorded_slot"]]
            episode = by_episode[candidate["episode_id"]]
            if not (
                episode["profile_id"] == candidate["profile_id"]
                and episode["first_second"]
                <= candidate["second"]
                <= episode["last_second"]
                and candidate["box"] == match["box"]
                and candidate["publisher_frame"] == match["publisher_frame"]
            ):
                raise ValueError("Candidate does not belong to its recorded episode")
            rows.append(
                {
                    **candidate,
                    "cow": match["cow"],
                    "episode_mixed": episode["mixed_animals"],
                    "episode_has_unmatched": episode["unmatched"] > 0,
                }
            )
        candidates[key] = {
            "summary": {
                **evidence_summary(rows),
                "from_mixed_episode": sum(row["episode_mixed"] for row in rows),
                "from_episode_with_unmatched": sum(
                    row["episode_has_unmatched"] for row in rows
                ),
            },
            "rows": rows,
        }
    return {
        "episodes": episodes,
        "profiles": [
            {"profile_id": key, **evidence_summary(rows)}
            for key, rows in profiles.items()
        ],
        "candidates": candidates,
        "totals": {
            "qualified_observations": len(matches),
            "qualified_unmatched": sum(row["cow"] is None for row in matches.values()),
            "episodes": len(episodes),
            "episodes_with_three_samples": sum(
                row["observations"] >= 3 for row in episodes
            ),
            "mixed_episodes": sum(row["mixed_animals"] for row in episodes),
            "episodes_with_unmatched": sum(row["unmatched"] > 0 for row in episodes),
            "fully_matched_single_animal_episodes": sum(
                row["fully_matched_single_animal"] for row in episodes
            ),
            "observations_in_mixed_episodes": sum(
                row["observations"] for row in episodes if row["mixed_animals"]
            ),
        },
    }


def freeze(path):
    inputs = [
        Path(__file__),
        ROOT / "test_anonymous_profile_audit.py",
        ROOT / "anonymous_profile_inventory.py",
        ROOT / "video_assessment.py",
        ROOT / "benchmark.py",
        INVENTORY,
        INVENTORY_PROTOCOL,
        RUN,
        CLIP,
        ANNOTATIONS,
        Path("detector/src/aidetector/domain/models.py"),
    ]
    write_json(
        path,
        {
            "status": "FROZEN_GEOMETRY_AUDIT_OF_COMPLETED_PREDICTION_ONLY_SELECTION",
            "files": {str(p): digest(p) for p in inputs},
            "range": [0, 2999],
            "method": "Use all same-frame raw tracked boxes in cardinality-first one-to-one IoU>=.5 matching before choosing qualified tracks. Audit all quality episodes and both the1546proposals/128retained separately. No known/unknown or initial names affect the matching or denominator; no new model calls, label-based photo selection, thresholds or merges. Unmatched observations stay failures. A common slot across episodes is only an observation-instance scope.",
            "limits": "Exposed public development recording; no fresh held-out result, new-farm claim, pixel-perfect mask ownership, readable tags, cross-camera matching or automatic biological enrollment. The maximum dominant-cow fraction is a diagnostic upper bound, not a predicted identity.",
        },
    )


def execute(protocol_path, output):
    protocol = json.loads(protocol_path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    inventory = json.loads(INVENTORY.read_text())
    if inventory["protocol_sha256"] != digest(INVENTORY_PROTOCOL):
        raise ValueError("The original label-blind selection is not bound")
    raw = json.loads(RUN.read_text())
    if not raw["complete"] or [f["second"] for f in raw["timeline"]] != list(
        range(3000)
    ):
        raise ValueError("Require the complete exact0–2999 prediction recording")
    clip = json.loads(CLIP.read_text())
    width, height = clip["width"], clip["height"]
    with np.load(ANNOTATIONS, allow_pickle=False) as archive:
        keep = archive["frame_id"] <= 59981
        records = {
            key: archive[key][keep]
            for key in ("frame_id", "cow_id", "x_center", "y_center", "width", "height")
        }
    matches = {}
    visible = Counter()
    for frame in raw["timeline"]:
        truth = truth_at(records, frame["publisher_frame"], width, height)
        visible.update(str(row["cow"]) for row in truth)
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        pairs = pair_boxes(boxes, truth, minimum=0.5)
        for index, box in enumerate(frame["boxes"]):
            if qualified(frame, box, width, height):
                matches[frame["second"], box["track_id"]] = {
                    "cow": truth[pairs[index]]["cow"] if index in pairs else None,
                    "publisher_frame": frame["publisher_frame"],
                    "box": [box[key] for key in ("x1", "y1", "x2", "y2")],
                }
    result = summarize(inventory, matches)
    if (
        result["totals"]["qualified_observations"]
        != inventory["counts"]["qualified_observations"]
    ):
        raise ValueError("The original observation count changed")
    write_json(
        output,
        {
            "status": "COMPLETE_GEOMETRY_AUDIT_NO_IDENTITY_ASSIGNMENT",
            "protocol_sha256": digest(protocol_path),
            "visible_annotations_per_animal": dict(visible),
            **result,
        },
    )
    print(json.dumps(result["totals"]))
    print(
        json.dumps(
            {key: value["summary"] for key, value in result["candidates"].items()}
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "audit"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.protocol if args.mode == "freeze" else args.output
    if destination is None or destination.exists():
        parser.error("Use a new immutable destination")
    freeze(args.protocol) if args.mode == "freeze" else execute(
        args.protocol, args.output
    )


if __name__ == "__main__":
    main()
