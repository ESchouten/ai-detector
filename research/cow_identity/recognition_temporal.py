"""Causal track evidence/persistence controls; publisher tracks are oracle inputs."""

import argparse
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_experiment import select_gallery
from scoring import Scores, metrics, normalize

POLICY = (
    "Research EMA/TTL variant, not production GalleryIdentifier: three accepted "
    "observations within five-second evidence gaps; unknown evidence may retain "
    "a confirmed name until TTL expires; collisions reject confirmed names. "
    "Production instead clears ambiguous evidence and rejects raw-candidate collisions."
)


def validate_timeline(rows):
    """One camera/window, frame-major order, at most one box per tracked object."""
    previous = None
    tracks = set()
    for row in rows:
        second, track = row["second"], row["track"]
        if not np.isfinite(second) or (previous is not None and second < previous):
            raise ValueError("Temporal rows need finite, nondecreasing timestamps")
        if second != previous:
            tracks.clear()
        if track is not None:
            if track in tracks:
                raise ValueError("A track has duplicate observations at one timestamp")
            tracks.add(track)
        previous = second


def smoothed_scores(rows, vectors, gallery, owners, alpha, geometry):
    validate_timeline(rows)
    classes = np.unique(owners)
    similarity = vectors @ gallery.T
    by_class = np.stack(
        [similarity[:, owners == cow].max(axis=1) for cow in classes], axis=1
    )
    filtered = np.full_like(by_class, -1)
    previous = {}
    for i, row in enumerate(rows):
        eligible = geometry == "none" or (
            row["minimum_side"] >= 64
            and not row["clipped"]
            and row["overlap"] <= float(geometry)
        )
        if not eligible:
            continue
        track = row["track"]
        old = previous.get(track) if track is not None else None
        current = by_class[i]
        if old and row["second"] - old[0] <= 5:
            current = alpha * current + (1 - alpha) * old[1]
        if track is not None:
            previous[track] = (row["second"], current)
        filtered[i] = current
    order = np.argsort(-filtered, axis=1, kind="stable")
    indexes = np.arange(len(rows))
    truth = np.array([row["cow"] for row in rows])
    return Scores(
        truth,
        classes[order[:, 0]],
        filtered[indexes, order[:, 0]],
        filtered[indexes, order[:, 0]] - filtered[indexes, order[:, 1]],
        np.isin(truth, classes),
        np.zeros(len(truth)),
    )


def clear_collisions(names, items, state):
    for name in set(names[j] for j, _ in items) - {0}:
        duplicates = [(j, identity) for j, identity in items if names[j] == name]
        if len(duplicates) > 1:
            for j, identity in duplicates:
                names[j] = 0
                state[identity]["name"] = 0
                state[identity]["candidate"] = 0
                state[identity]["count"] = 0


def update_track(state, row, candidate, ttl):
    track, second = row["track"], row["second"]
    if track is None:
        return 0
    current = state.get(track)
    if current is None or second - current["seen"] > 2:
        current = {
            "seen": second,
            "candidate": 0,
            "count": 0,
            "evidence": second,
            "name": 0,
            "confirmed": second,
        }
        state[track] = current
    current["seen"] = second
    if candidate:
        if current["name"] and current["name"] != candidate:
            current["name"] = 0
        if candidate == current["candidate"] and second - current["evidence"] <= 5:
            current["count"] += 1
        else:
            current["candidate"], current["count"] = candidate, 1
        current["evidence"] = second
        if current["count"] >= 3:
            current["name"], current["confirmed"] = candidate, second
    if second - current["confirmed"] > ttl:
        current["name"] = 0
    return current["name"]


def temporal_names(rows, scores, threshold, margin, ttl):
    validate_timeline(rows)
    accepted = (scores.similarity >= threshold) & (scores.margin >= margin)
    names = np.zeros(len(rows), dtype=int)
    state = {}
    frame_outputs = {}
    for i, row in enumerate(rows):
        candidate = int(scores.predicted[i]) if accepted[i] else 0
        names[i] = update_track(state, row, candidate, ttl)
        second = row["second"]
        frame_outputs.setdefault(second, []).append((i, row["track"]))
        # Rows arrive frame-major; collision rejection after each frame also
        # clears both histories before their next observation.
        if i + 1 == len(rows) or rows[i + 1]["second"] != second:
            clear_collisions(names, frame_outputs.pop(second), state)
    return names


def decision_metrics(rows, scores, threshold, margin, ttl):
    names = temporal_names(rows, scores, threshold, margin, ttl)
    named = names != 0
    result = metrics(
        Scores(
            scores.truth,
            names,
            np.where(named, 1, -1),
            np.ones(len(rows)),
            scores.known,
            scores.cameras,
        ),
        0,
        0,
    )
    result.pop("known_rank1")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    with np.load(args.run / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    selected = select_gallery(manifest["rows"], vectors, "diverse10")
    gallery = vectors[selected]
    owners = np.array([manifest["rows"][i]["cow"] for i in selected])
    results = {}
    for alpha in (1.0, 0.5, 0.2):
        for geometry in ("none", "0.2", "0.5"):
            panels = {}
            for split in ("development", "development_later", "calibration"):
                indices = [
                    i for i, row in enumerate(manifest["rows"]) if row["panel"] == split
                ]
                rows = [
                    {**manifest["rows"][i], "track": manifest["rows"][i]["cow"]}
                    for i in indices
                ]
                panels[split] = (
                    rows,
                    smoothed_scores(
                        rows, vectors[indices], gallery, owners, alpha, geometry
                    ),
                )
            for ttl in (0, 10, 30, 60):
                best = (0, 1.01, 1.01)
                for threshold in (0.4, 0.5, 0.55, 0.6, 0.65, 0.7):
                    for margin in (0.05, 0.1, 0.15, 0.2):
                        counts = decision_metrics(
                            *panels["calibration"], threshold, margin, ttl
                        )
                        if (counts["accepted_precision"] or 0) >= 0.99 and counts[
                            "unknown_false_acceptance_rate"
                        ] <= 0.01:
                            best = max(
                                best, (counts["correct_accepts"], threshold, margin)
                            )
                _, threshold, margin = best
                name = f"ema{alpha}-geometry{geometry}-ttl{ttl}"
                results[name] = {
                    "threshold": threshold,
                    "margin": margin,
                    "panels": {
                        split: decision_metrics(*panel, threshold, margin, ttl)
                        for split, panel in panels.items()
                    },
                }
    write_json(
        args.run / "temporal.json",
        {
            "manifest_sha256": digest(args.run / "manifest.json"),
            "limitation": "Oracle publisher tracks; cannot establish actual tracker safety or application accuracy",
            "policy": POLICY,
            "conditions": results,
        },
    )
    for name, result in results.items():
        print(
            name,
            json.dumps(
                {
                    split: [
                        round(panel[key], 4) if panel[key] is not None else None
                        for key in (
                            "accepted_precision",
                            "known_coverage",
                            "unknown_false_acceptance_rate",
                        )
                    ]
                    for split, panel in result["panels"].items()
                }
            ),
        )


if __name__ == "__main__":
    main()
