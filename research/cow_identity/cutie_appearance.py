"""Corroborate seeded mask tracks using cached appearance, selecting on calibration."""

import argparse
import itertools
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from detection_sam_tracking import score
from video_assessment import annotations

from aidetector.domain.models import BoundingBox


def read_features(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if digest(directory / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Feature vectors differ from their recorded hash")
    with np.load(directory / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    if (
        vectors.ndim != 2
        or len(vectors) != len(manifest["rows"])
        or not np.isfinite(vectors).all()
        or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=0.001)
    ):
        raise ValueError("Expected one finite normalized vector per observation")
    return manifest, vectors


def validate_features(features, propagation, protocol, width, height):
    expected = [
        second
        for start, end in protocol["feature_windows"]
        for second in range(start, end + 1)
    ]
    frames, rows = features["frames"], features["rows"]
    if [frame["second"] for frame in frames] != expected:
        raise ValueError("Features must cover every frozen timestamp exactly once")
    if [index for frame in frames for index in frame["rows"]] != list(range(len(rows))):
        raise ValueError("Frame rows must enumerate every observation exactly once")
    source_frames = {frame["second"]: frame for frame in propagation["timeline"]}
    for frame in frames:
        source = source_frames[frame["second"]]
        statistics = {item["track_id"]: item for item in source["objects"]}
        tracks = set()
        for index in frame["rows"]:
            row = rows[index]
            track = row["track_id"]
            if (
                track in tracks
                or track not in statistics
                or row["second"] != frame["second"]
            ):
                raise ValueError(
                    "Feature rows changed the original object slots or timestamps"
                )
            tracks.add(track)
            if (
                row["mask_sha256"] != source["mask_sha256"]
                or row["p10_probability"] != statistics[track]["p10_probability"]
                or not np.isfinite(row["p10_probability"])
                or not 0 <= row["p10_probability"] <= 1
            ):
                raise ValueError("Appearance evidence differs from its original mask")
            x1, y1, x2, y2 = row["box"]
            if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
                raise ValueError("Invalid predicted mask box")


def appearance_evidence(rows, queries, gallery_rows, gallery, seeds, named_cows):
    """Only known seed names are candidates; a better alternative is veto evidence."""
    owners = np.array([row["cow"] for row in gallery_rows])
    similarities = np.clip(queries @ gallery.T, -1, 1)
    scores = np.column_stack(
        [similarities[:, owners == cow].max(axis=1) for cow in named_cows]
    )
    positions = {cow: index for index, cow in enumerate(named_cows)}
    evidence = []
    for row, values in zip(rows, scores, strict=True):
        cow = seeds[row["track_id"]]["cow"]
        if cow not in positions:
            evidence.append(None)
            continue
        index = positions[cow]
        own = float(values[index])
        other = float(np.delete(values, index).max())
        evidence.append({"own_similarity": own, "own_minus_other": own - other})
    return evidence


def allowed_names(features, evidence, condition, window):
    """Carry only chronological prior evidence; a scoring boundary is not a reset."""
    streaks, allowed = {}, set()
    previous = None
    for frame in features["frames"]:
        second = frame["second"]
        if second > window[1]:
            break
        if previous is None or second != previous + 1:
            streaks.clear()
        current = {}
        for index in frame["rows"]:
            row, appearance = features["rows"][index], evidence[index]
            if appearance is None or not (
                row["p10_probability"] >= condition["minimum_p10_probability"]
                and appearance["own_similarity"] >= condition["minimum_own_similarity"]
                and appearance["own_minus_other"]
                >= condition["minimum_own_minus_other"]
            ):
                continue
            track = row["track_id"]
            current[track] = streaks.get(track, 0) + 1
            if (
                second >= window[0]
                and current[track] >= condition["consecutive_passes"]
            ):
                allowed.add((second, track))
        streaks, previous = current, second
    return allowed


def predicted_timeline(propagation, features):
    """Use the same largest-component boxes as the encoded pixels, including unknowns."""
    replacements = {
        frame["second"]: [
            asdict(
                BoundingBox(
                    *features["rows"][index]["box"],
                    "cow",
                    1.0,
                    features["rows"][index]["track_id"],
                )
            )
            for index in frame["rows"]
        ]
        for frame in features["frames"]
    }
    return {
        **propagation,
        "timeline": [
            {**frame, "boxes": replacements.get(frame["second"], frame["boxes"])}
            for frame in propagation["timeline"]
        ],
    }


def measure(
    value,
    features,
    evidence,
    condition,
    window,
    records,
    clip,
    tracking,
    blocked_names=frozenset(),
):
    allowed = allowed_names(features, evidence, condition, window) - blocked_names
    metrics = score(
        value,
        records,
        clip,
        {**tracking, "score_seconds": window},
        value["provenance"]["seed_prompts"],
        name_allowed=lambda frame, box: (frame["second"], box.track_id) in allowed,
    )
    counts = metrics["naming_counts"]
    return {
        "condition": condition,
        "metrics": metrics,
        "unknown_false_naming_rate": counts["unknown_named"]
        / counts["visible_unknown"],
    }


def choose(results, minimum_coverage=0.6):
    qualified = [
        row
        for row in results
        if row["metrics"]["conservative_precision"] >= 0.99
        and row["unknown_false_naming_rate"] <= 0.01
    ]
    if not qualified:
        return {"selected": None, "meets_all_gates": False}
    selected = min(
        qualified,
        key=lambda row: (
            -row["metrics"]["known_coverage"],
            -row["metrics"]["conservative_precision"],
            row["condition"]["consecutive_passes"],
            row["condition"]["minimum_p10_probability"],
            row["condition"]["minimum_own_similarity"],
            row["condition"]["minimum_own_minus_other"],
        ),
    )
    return {
        "selected": selected,
        "meets_all_gates": selected["metrics"]["known_coverage"] >= minimum_coverage,
    }


def load_inputs(args):
    protocol = json.loads(args.protocol.read_text())
    tracking = json.loads(args.tracking_protocol.read_text())
    propagation = json.loads(args.propagation.read_text())
    clip = json.loads(args.sampled_manifest.read_text())
    features, queries = read_features(args.features)
    reference, gallery = read_features(args.gallery)
    bindings = (
        (args.propagation, protocol["propagation_sha256"]),
        (args.sampled_manifest, protocol["sampled_manifest_sha256"]),
        (args.gallery / "manifest.json", protocol["gallery_manifest_sha256"]),
        (args.gallery / "vectors.npz", protocol["gallery_vectors_sha256"]),
        (args.source_pickle, tracking["source_annotations_sha256"]),
        (args.annotations, reference["contract"]["origin"]["annotations_sha256"]),
        (args.protocol, features["contract"]["protocol_sha256"]),
        (args.tracking_protocol, propagation["provenance"]["protocol_sha256"]),
    )
    if any(digest(path) != expected for path, expected in bindings):
        raise ValueError("Frozen appearance inputs changed")
    if (
        not propagation["complete"]
        or protocol["selection_window"] != [1230, 1529]
        or protocol["feature_windows"] != [[330, 629], [930, 1229], [1230, 1529]]
        or protocol["development_replay_windows"] != [[330, 629], [930, 1229]]
        or tracking["last_processed_second"] != 1529
        or clip["contract"]["video_sha256"] != tracking["video_sha256"]
        or features["contract"]["runner_sha256"] != protocol["runner_sha256"]
    ):
        raise ValueError("Incomplete or unexpected frozen appearance protocol")
    # The gallery's outer fingerprint also binds its SAM crop provenance. Compare
    # the actual encoder, while retaining both distinct mask contracts in output.
    if (
        reference["contract"]["representation"]["encoder_fingerprint"]
        != features["contract"]["encoder_fingerprint"]
        or gallery.shape[1] != queries.shape[1]
    ):
        raise ValueError("Gallery and query encoder fingerprints or dimensions differ")
    known = tracking["named_cows"]
    if (
        len(reference["rows"]) != 10 * len(known)
        or any(
            row["panel"] != "enrollment" or not 0 <= row["second"] < 300
            for row in reference["rows"]
        )
        or any(
            sum(row["cow"] == cow for row in reference["rows"]) != 10 for cow in known
        )
        or [row["cow"] for row in propagation["provenance"]["seed_prompts"]]
        != tracking["seeded_cows"]
    ):
        raise ValueError("Confirmed early gallery or original seed identities changed")
    validate_features(features, propagation, protocol, clip["width"], clip["height"])
    return protocol, tracking, propagation, clip, features, queries, reference, gallery


def read_quarantine(args):
    if args.quarantine is None and args.combination_protocol is None:
        return frozenset(), None
    if args.quarantine is None or args.combination_protocol is None:
        raise ValueError(
            "Quarantine requires its separately frozen combination protocol"
        )
    rules = json.loads(args.combination_protocol.read_text())
    report = json.loads(args.quarantine.read_text())
    if (
        digest(args.quarantine) != rules["quarantine_report_sha256"]
        or digest(args.protocol) != rules["appearance_protocol_sha256"]
        or digest(args.propagation) != report["propagation_sha256"]
    ):
        raise ValueError("Frozen quarantine combination inputs changed")
    conflicts = report["conflicted_ids_by_second"]
    if list(map(int, conflicts)) != list(range(1530)) or any(
        slots != sorted(set(slots)) or not set(slots).issubset(range(1, 9))
        for slots in conflicts.values()
    ):
        raise ValueError(
            "Quarantine must retain every timestamp and original object slot"
        )
    return frozenset(
        (int(second), slot - 1) for second, slots in conflicts.items() for slot in slots
    ), {**rules, "protocol_sha256": digest(args.combination_protocol)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
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
    parser.add_argument("--quarantine", type=Path)
    parser.add_argument("--combination-protocol", type=Path)
    args = parser.parse_args()
    protocol, tracking, propagation, clip, features, queries, reference, gallery = (
        load_inputs(args)
    )
    evidence = appearance_evidence(
        features["rows"],
        queries,
        reference["rows"],
        gallery,
        propagation["provenance"]["seed_prompts"],
        tracking["named_cows"],
    )
    value = predicted_timeline(propagation, features)
    blocked, combination = read_quarantine(args)
    records, _ = annotations(args)
    grid = protocol["grid"]
    results = [
        measure(
            value,
            features,
            evidence,
            dict(zip(grid, values, strict=True)),
            protocol["selection_window"],
            records,
            clip,
            tracking,
            blocked,
        )
        for values in itertools.product(*grid.values())
    ]
    selection = choose(results)
    replays = {}
    if selection["selected"] is not None:
        condition = selection["selected"]["condition"]
        replays = {
            f"{window[0]}-{window[1]}": measure(
                value,
                features,
                evidence,
                condition,
                window,
                records,
                clip,
                tracking,
                blocked,
            )
            for window in protocol["development_replay_windows"]
        }
    write_json(
        args.output,
        {
            "scope": "Calibration-only appearance veto of manually seeded tracks; no reassignment, final test or production claim",
            "protocol_sha256": digest(args.protocol),
            "features_manifest_sha256": digest(args.features / "manifest.json"),
            "gallery_manifest_sha256": digest(args.gallery / "manifest.json"),
            "propagation_sha256": digest(args.propagation),
            "annotations_sha256": digest(args.annotations),
            "runner_sha256": digest(Path(__file__)),
            "scorer_sha256": digest(
                Path(__file__).with_name("detection_sam_tracking.py")
            ),
            "counter_initialization": "Causal streaks over available chronological one-second evidence; missing frame/slot or failed evidence resets. A scoring boundary does not reset past evidence; no truth enters the counters.",
            "quarantine_combination": combination,
            "gallery_contract": reference["contract"],
            "query_contract": features["contract"],
            "conditions": results,
            **selection,
            "development_replays": replays,
        },
    )
    print(json.dumps({**selection, "development_replays": replays}))


if __name__ == "__main__":
    main()
