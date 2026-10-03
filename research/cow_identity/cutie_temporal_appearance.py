"""Replay frozen causal appearance pooling on the original mask-track evidence."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from cutie_appearance import (
    appearance_evidence,
    choose,
    load_inputs,
    measure,
    predicted_timeline,
)
from video_assessment import annotations


def smooth_vectors(features, vectors, alpha):
    """Each original slot gets only its own past evidence; gaps discard memory."""
    if alpha == 1:
        return vectors.copy()
    result = np.empty_like(vectors)
    state = {}
    previous = None
    for frame in features["frames"]:
        second = frame["second"]
        if previous is None or second != previous + 1:
            state.clear()
        current = {}
        for index in frame["rows"]:
            track = features["rows"][index]["track_id"]
            vector = vectors[index]
            if track in state:
                vector = alpha * vector + (1 - alpha) * state[track]
                norm = np.linalg.norm(vector)
                if norm == 0:
                    raise ValueError("Opposite feature vectors canceled completely")
                vector = vector / norm
            current[track] = vector
            result[index] = vector
        state, previous = current, second
    return result


def evaluate(args):
    temporal = json.loads(args.temporal_protocol.read_text())
    bindings = (
        (args.protocol, temporal["appearance_protocol_sha256"]),
        (args.features / "manifest.json", temporal["features_manifest_sha256"]),
        (Path(__file__), temporal["runner_sha256"]),
    )
    if any(digest(path) != expected for path, expected in bindings):
        raise ValueError("Frozen temporal control inputs changed")
    protocol, tracking, propagation, clip, features, queries, reference, gallery = (
        load_inputs(args)
    )
    value = predicted_timeline(propagation, features)
    records, _ = annotations(args)
    results, evidence_by_alpha = [], {}
    for alpha in temporal["ema_alphas"]:
        pooled = smooth_vectors(features, queries, alpha)
        evidence = appearance_evidence(
            features["rows"],
            pooled,
            reference["rows"],
            gallery,
            propagation["provenance"]["seed_prompts"],
            tracking["named_cows"],
        )
        evidence_by_alpha[alpha] = evidence
        grid = protocol["grid"]
        for values in itertools.product(*grid.values()):
            condition = {**dict(zip(grid, values, strict=True)), "ema_alpha": alpha}
            results.append(
                measure(
                    value,
                    features,
                    evidence,
                    condition,
                    protocol["selection_window"],
                    records,
                    clip,
                    tracking,
                )
            )
    selection = choose(results)
    replays = {}
    if selection["selected"] is not None:
        condition = selection["selected"]["condition"]
        evidence = evidence_by_alpha[condition["ema_alpha"]]
        replays = {
            f"{window[0]}-{window[1]}": measure(
                value, features, evidence, condition, window, records, clip, tracking
            )
            for window in protocol["development_replay_windows"]
        }
    result = {
        "scope": "Exploratory calibration after the single-frame control; exposed development replay, no reserved footage or deployment claim",
        "protocol_sha256": digest(args.temporal_protocol),
        "appearance_protocol_sha256": digest(args.protocol),
        "features_manifest_sha256": digest(args.features / "manifest.json"),
        "runner_sha256": digest(Path(__file__)),
        "conditions": results,
        **selection,
        "development_replays": replays,
    }
    write_json(args.output, result)
    print(json.dumps({**selection, "development_replays": replays}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "temporal-protocol",
        "protocol",
        "tracking-protocol",
        "propagation",
        "sampled-manifest",
        "features",
        "gallery",
        "annotations",
        "source-pickle",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    evaluate(parser.parse_args())


if __name__ == "__main__":
    main()
