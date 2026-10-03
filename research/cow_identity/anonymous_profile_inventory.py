"""Prediction-only bounded photo candidates from automatic anonymous startup."""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json

ROOT = Path(__file__).parent
RUN = Path(".cache/cow-startup-extended/streaming.json")
CLIP = Path(".cache/cow-cutie/reserved-2fps-clip/sampled.json")
REPORT = ROOT / "results/2026-10-03/detection/startup-extended-independent-audit.json"


def identifier(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def qualified(frame, box, width, height):
    track = box["track_id"]
    quality = next(item for item in frame["objects"] if item["track_id"] == track)
    x1, y1, x2, y2 = (box[k] for k in ("x1", "y1", "x2", "y2"))
    return (
        track + 1 not in frame["conflicted_ids"]
        and any(pair["track_id"] == track for pair in frame["reciprocal_pairs"])
        and quality["p10_probability"] is not None
        and quality["p10_probability"] >= 0.7
        and x1 >= 1
        and y1 >= 1
        and x2 < width - 1
        and y2 < height - 1
        and min(x2 - x1, y2 - y1) >= 64
    )


def view_vector(row, width, height):
    x1, y1, x2, y2 = row["box"]
    return (
        math.log2((x2 - x1) / (y2 - y1)),
        math.sqrt(row["area"] / (width * height)),
        (x1 + x2) / (2 * width),
        (y1 + y2) / (2 * height),
    )


def bounded_views(rows, width, height, maximum=16):
    """Online current-reservoir plus one; geometry proxy, never identity evidence."""
    if len(rows) <= maximum:
        return rows
    values = np.array([view_vector(row, width, height) for row in rows])
    distances = np.linalg.norm(values[:, None] - values[None, :], axis=2)
    selected = [int(distances.mean(axis=1).argmin())]
    while len(selected) < maximum:
        novelty = distances[:, selected].min(axis=1)
        novelty[selected] = -1
        selected.append(int(novelty.argmax()))
    return [rows[i] for i in sorted(selected)]


def inventory(timeline, context, width, height):
    profiles, active, episodes, retained = {}, {}, [], {}
    proposals, last_candidate = [], {}
    for frame in timeline:
        second = frame["second"]
        current = set()
        for box in frame["boxes"]:
            if not qualified(frame, box, width, height):
                continue
            track = box["track_id"]
            current.add(track)
            if track not in profiles:
                profiles[track] = {
                    **context,
                    "instance_id": identifier(context["run_id"], "slot", track),
                    "generation": 1,
                    "recorded_slot": track,
                    "status": "anonymous_observation_instance_not_biological_identity",
                }
                profiles[track]["profile_id"] = identifier(profiles[track])
                retained[track] = []
            previous = active.get(track)
            if previous is None or previous["last_second"] != second - 1:
                previous = {
                    "episode_id": identifier(profiles[track]["profile_id"], second),
                    "profile_id": profiles[track]["profile_id"],
                    "recorded_slot": track,
                    "first_second": second,
                    "last_second": second,
                    "qualified_observations": 0,
                }
                episodes.append(previous)
            previous["last_second"] = second
            previous["qualified_observations"] += 1
            active[track] = previous
            if (
                previous["qualified_observations"] < 3
                or second - last_candidate.get(track, -math.inf) < 10
            ):
                continue
            quality = next(i for i in frame["objects"] if i["track_id"] == track)
            row = {
                "profile_id": profiles[track]["profile_id"],
                "episode_id": previous["episode_id"],
                "recorded_slot": track,
                "second": second,
                "publisher_frame": frame["publisher_frame"],
                "box": [box[k] for k in ("x1", "y1", "x2", "y2")],
                "area": quality["area"],
                "mask_p10": quality["p10_probability"],
                "source_pixels_sha256": frame["source_pixels_sha256"],
                "mask_sha256": frame["mask_sha256"],
            }
            last_candidate[track] = second
            proposals.append(row)
            retained[track] = bounded_views([*retained[track], row], width, height)
        active = {track: state for track, state in active.items() if track in current}
    return {
        "profiles": list(profiles.values()),
        "episodes": episodes,
        "candidate_observations": proposals,
        "retained_candidates": [r for rows in retained.values() for r in rows],
        "counts": {
            "profiles": len(profiles),
            "qualified_episodes": len(episodes),
            "qualified_observations": sum(
                r["qualified_observations"] for r in episodes
            ),
            "episodes_at_least_three": sum(
                r["qualified_observations"] >= 3 for r in episodes
            ),
            "candidate_observations": len(proposals),
            "retained_candidates": sum(len(rows) for rows in retained.values()),
            "retained_per_slot": dict(
                Counter(r["recorded_slot"] for rows in retained.values() for r in rows)
            ),
        },
    }


def freeze(path):
    files = [
        Path(__file__),
        ROOT / "test_anonymous_profile_inventory.py",
        RUN,
        CLIP,
        REPORT,
    ]
    write_json(
        path,
        {
            "status": "FROZEN_PREDICTION_ONLY_SELECTION_NO_INFERENCE_OR_LABELS",
            "files": {str(p): digest(p) for p in files},
            "input_run": str(RUN),
            "clip_metadata": str(CLIP),
            "range": [0, 2999],
            "rules": "All original slots, no known/unknown distinction. Existing p10>=.7, reciprocal partner, no quarantine, unclipped>=64px quality; consecutive1Hz episodes break at every quality/missing-frame gap. Three eligible observations before first photo, >=10s between candidates perinstance. At most16 current candidates via Euclidean geometry medoid/farthest-first over current16+new1 (log2aspect,sqrtforegroundfraction,normalizedcenterXY), chronologicalties. No descriptor/identity comparison or transitive links.",
            "semantics": "The profile key groups one recorded observation instance only. Episodes remain separate provenance; neither common slot nor candidate similarity certifies biological identity. Runtime UUID/epoch/generation are not present in this offline recording; namespace keys are explicit synthetic equivalents bound to exact run+source hashes.",
            "evaluation": "Selection consumes prediction-only allowed fields; report counts and boundedness first. Future label audit may quantify cross-animal episode contamination, duplicate instance profiles, and same-frame false merges. There are no cross-profile merges in this inventory; zero implemented merges is not proof of biological continuity or recognition coverage.",
        },
    )


def execute(path, output):
    protocol = json.loads(path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Bound input changed: {name}")
    raw = json.loads(Path(protocol["input_run"]).read_text())
    clip = json.loads(Path(protocol["clip_metadata"]).read_text())
    if not raw["complete"] or [f["second"] for f in raw["timeline"]] != list(
        range(3000)
    ):
        raise ValueError("Complete exact0–2999 recording required")
    keys = (
        "second",
        "publisher_frame",
        "boxes",
        "objects",
        "reciprocal_pairs",
        "conflicted_ids",
        "source_pixels_sha256",
        "mask_sha256",
    )
    frames = [{key: f[key] for key in keys} for f in raw["timeline"]]
    context = {
        "run_id": digest(Path(protocol["input_run"])),
        "source_key": clip["contract"]["video_sha256"],
        "epoch": "offline-contiguous-recording-0",
        "provenance": "synthetic-offline-scope-not-a-runtime-UUID",
    }
    result = inventory(frames, context, clip["width"], clip["height"])
    write_json(
        output,
        {
            "protocol_sha256": digest(path),
            "status": "COMPLETE_SELECTION_ONLY",
            **result,
        },
    )
    print(json.dumps(result["counts"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "inventory"))
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
