"""Evaluate causal naming on cached real detector tracks, with missed-cow counts."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_experiment import select_gallery
from recognition_temporal import (
    POLICY,
    smoothed_scores,
    temporal_names,
    validate_timeline,
)
from scoring import normalize

PROTOCOL = Path(__file__).with_name("recognition_protocol.json")


def protocol_windows(protocol):
    return {
        "enrollment": range(
            protocol["enrollment"]["seconds"][0],
            protocol["enrollment"]["seconds"][1] + 1,
            protocol["enrollment"]["sample_every_seconds"],
        ),
        **{
            name: range(start, end + 1)
            for name, (start, end) in zip(
                ("development", "development_later", "calibration"),
                [*protocol["development_windows"], protocol["calibration_window"]],
                strict=True,
            )
        },
    }


def validate_gallery(manifest, protocol):
    contract = manifest["contract"].get("origin", manifest["contract"])
    if (
        contract["video_sha256"] != protocol["video_sha256"]
        or contract["source_sha256"] != protocol["source_pickle_sha256"]
        or contract["enrolled_ids"] != protocol["known_ids"]
        or contract["unknown_ids"] != protocol["unknown_ids"]
    ):
        raise ValueError("Gallery source or identities differ from the frozen protocol")
    windows = protocol_windows(protocol)
    for panel, seconds in contract["panels"].items():
        if panel not in windows or not set(seconds) <= set(windows[panel]):
            raise ValueError(
                "Gallery archive declares observations outside allowed windows"
            )
    observed = set()
    for row in manifest["rows"]:
        panel, second, cow = row["panel"], row["second"], row["cow"]
        if panel not in windows or second not in windows[panel]:
            raise ValueError(
                "Gallery archive contains rows outside the allowed windows"
            )
        if row["frame"] != second * 20 + 1:
            raise ValueError("Gallery rows do not match the publisher source frame")
        allowed = protocol["known_ids"] if panel == "enrollment" else range(1, 9)
        if cow not in allowed:
            raise ValueError("Unknown identities cannot enter enrollment")
        key = (panel, second, cow)
        if key in observed:
            raise ValueError("Gallery archive contains duplicate cow observations")
        observed.add(key)


def validate_panel(manifest, gallery_manifest, name, protocol):
    """Reject mislabeled caches before they can alter denominators or agreement."""
    provenance = manifest["contract"]["tracking_provenance"]
    expected = protocol_windows(protocol)[name]
    gallery = gallery_manifest["contract"].get("origin", gallery_manifest["contract"])
    if (
        provenance["video"] != protocol["video_sha256"]
        or provenance["annotations"] != gallery["annotations_sha256"]
    ):
        raise ValueError("Tracking video or annotations differ from the gallery source")
    if (
        provenance["start"] != expected.start
        or provenance["seconds"] != len(expected)
        or provenance["scoring_fps"] != protocol["query_fps"]
        or [frame["second"] for frame in manifest["frames"]] != list(expected)
    ):
        raise ValueError("Tracking frames do not match the complete frozen window")
    rows, frames = manifest["rows"], manifest["frames"]
    if [index for frame in frames for index in frame["rows"]] != list(range(len(rows))):
        raise ValueError("Every predicted box must occur exactly once in its frame")
    validate_timeline(rows)
    for frame in frames:
        truth = [item["cow"] for item in frame["truth"]]
        if len(set(truth)) != len(truth) or not set(truth) <= set(range(1, 9)):
            raise ValueError("Each annotated cow must occur at most once per frame")
        matched = []
        for index in frame["rows"]:
            row = rows[index]
            if (
                row["second"] != frame["second"]
                or row["frame"] != 20 * frame["second"] + 1
            ):
                raise ValueError("Predicted rows do not match their source frame")
            if row["truth"] is not None:
                matched.append(row["truth"])
        if len(set(matched)) != len(matched) or not set(matched) <= set(truth):
            raise ValueError("Truth association must be one-to-one within the frame")


def validate_representation(gallery_manifest, manifest, name):
    gallery, queries = gallery_manifest["contract"], manifest["contract"]
    key = "representation_fingerprint"
    if (key in gallery) != (key in queries):
        raise ValueError(f"{name} and gallery mix derived and original representations")
    if key not in gallery:
        key = "encoder_fingerprint"
    if gallery[key] != queries[key]:
        raise ValueError(f"{name} and gallery use different representations")


def read_features(path):
    manifest = json.loads((path / "manifest.json").read_text())
    if digest(path / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Feature cache changed")
    with np.load(path / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    if len(vectors) != len(manifest["rows"]):
        raise ValueError("Feature rows do not match the manifest")
    return manifest, vectors


def summarize(manifest, names):
    rows = manifest["rows"]
    truth = np.array([row["truth"] if row["truth"] is not None else -1 for row in rows])
    named = names != 0
    matched = truth != -1
    known = np.isin(truth, np.arange(1, 7))
    correct = named & matched & (names == truth)
    visible = Counter(
        item["cow"] for frame in manifest["frames"] for item in frame["truth"]
    )
    visible_known = sum(visible[cow] for cow in range(1, 7))
    visible_unknown = sum(
        count for cow, count in visible.items() if cow not in range(1, 7)
    )
    counts = {
        "visible_known": visible_known,
        "visible_unknown": visible_unknown,
        "predicted_boxes": len(rows),
        "matched_boxes": int(matched.sum()),
        "missed_annotations": sum(visible.values()) - int(matched.sum()),
        "correct_names": int(correct.sum()),
        "wrong_known_names": int((named & known & ~correct).sum()),
        "unknown_named": int((named & matched & ~known).sum()),
        "unmatched_named": int((named & ~matched).sum()),
    }
    return {
        "counts": counts,
        "known_coverage": counts["correct_names"] / visible_known
        if visible_known
        else None,
        "precision_on_matched": counts["correct_names"] / int((named & matched).sum())
        if (named & matched).any()
        else None,
        "precision_lower_bound": counts["correct_names"] / int(named.sum())
        if named.any()
        else None,
        "unknown_false_acceptance_rate": counts["unknown_named"] / visible_unknown
        if visible_unknown
        else None,
        "per_cow": {
            str(cow): {
                "visible": count,
                "matched": int((truth == cow).sum()),
                "correct_names": int((correct & (truth == cow)).sum()),
                "wrong_names": int((named & ~correct & (truth == cow)).sum()),
            }
            for cow, count in sorted(visible.items())
        },
    }


def calibrate_real_tracks(manifest, panel, ttl):
    best = (0, 1.01, 1.01)
    for threshold in (0.4, 0.5, 0.55, 0.6, 0.65, 0.7):
        for margin in (0.05, 0.1, 0.15, 0.2):
            names = temporal_names(*panel, threshold, margin, ttl)
            metrics = summarize(manifest, names)
            unknown_rate = metrics["unknown_false_acceptance_rate"]
            if (
                (metrics["precision_lower_bound"] or 0) >= 0.99
                and unknown_rate is not None
                and unknown_rate <= 0.01
            ):
                best = max(
                    best, (metrics["counts"]["correct_names"], threshold, margin)
                )
    return best[1], best[2]


def select_references(args, manifest, vectors):
    path = getattr(args, "gallery_selection", None)
    if path is None:
        return select_gallery(manifest["rows"], vectors, "diverse10"), {
            "method": "own diverse10"
        }
    selection = json.loads(path.read_text())
    if selection["source_manifest_sha256"] != digest(args.gallery / "manifest.json"):
        raise ValueError("Fixed reference selection belongs to another gallery")
    indices = selection["rows"]
    if any(
        type(i) is not int or not 0 <= i < len(manifest["rows"]) for i in indices
    ) or len(set(indices)) != len(indices):
        raise ValueError("Fixed reference indexes must be valid and unique")
    rows = [manifest["rows"][i] for i in indices]
    counts = Counter(row["cow"] for row in rows)
    if (
        any(row["panel"] != "enrollment" for row in rows)
        or set(counts) != set(range(1, 7))
        or max(counts.values()) > 10
    ):
        raise ValueError(
            "Fixed references must use at most10 early photos per known cow"
        )
    return np.asarray(indices), {
        "method": selection["selection"],
        "selection_sha256": digest(path),
    }


def evaluate(args):
    protocol = json.loads(PROTOCOL.read_text())
    gallery_manifest, gallery_vectors = read_features(args.gallery)
    validate_gallery(gallery_manifest, protocol)
    references = getattr(args, "enrollment_references", None)
    if references:
        from recognition_tracked_enrollment import read_references

        if args.development is not None:
            raise ValueError("Additional enrollment cannot also be a query window")
        gallery, owners, selection = read_references(
            references, args.gallery, gallery_manifest, gallery_vectors, protocol
        )
        selected = None
    else:
        selected, selection = select_references(args, gallery_manifest, gallery_vectors)
        gallery = gallery_vectors[selected]
        owners = np.array([gallery_manifest["rows"][i]["cow"] for i in selected])
    inputs = {
        name: read_features(path)
        for name, path in (
            ("calibration", args.calibration),
            ("development", args.development),
            ("development_later", args.development_later),
        )
        if path is not None
    }
    expected = gallery_manifest["contract"]["encoder_fingerprint"]
    for name, (manifest, _) in inputs.items():
        validate_panel(manifest, gallery_manifest, name, protocol)
        validate_representation(gallery_manifest, manifest, name)
    variants = {}
    for alpha in (1.0, 0.5, 0.2):
        for geometry in ("none", "0.2", "0.5"):
            panels = {}
            for name, (manifest, vectors) in inputs.items():
                rows = [
                    {**row, "cow": row["truth"] if row["truth"] is not None else -1}
                    for row in manifest["rows"]
                ]
                panels[name] = (
                    rows,
                    smoothed_scores(rows, vectors, gallery, owners, alpha, geometry),
                )
            for ttl in (0, 10, 30, 60):
                threshold, margin = calibrate_real_tracks(
                    inputs["calibration"][0], panels["calibration"], ttl
                )
                key = f"ema{alpha}-geometry{geometry}-ttl{ttl}"
                variants[key] = {
                    "threshold": threshold,
                    "margin": margin,
                    "panels": {
                        name: summarize(
                            inputs[name][0],
                            temporal_names(*panel, threshold, margin, ttl),
                        )
                        for name, panel in panels.items()
                    },
                }
    return {
        "status": "Development only; real detector boxes/tracks, no final evaluation",
        "protocol_sha256": digest(PROTOCOL),
        "temporal_policy": POLICY,
        "gallery_manifest_sha256": digest(args.gallery / "manifest.json"),
        "gallery_rows": selected.tolist() if selected is not None else None,
        "gallery_selection": selection,
        "encoder_fingerprint": expected,
        "representation_fingerprint": gallery_manifest["contract"].get(
            "representation_fingerprint"
        ),
        "inputs": {
            name: manifest["contract"] for name, (manifest, _) in inputs.items()
        },
        "precision_policy": "Calibration treats every named unmatched detection as incorrect; matched precision also reported separately",
        "conditions": variants,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gallery", "calibration", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--development-later", type=Path)
    references = parser.add_mutually_exclusive_group()
    references.add_argument("--gallery-selection", type=Path)
    references.add_argument("--enrollment-references", type=Path)
    args = parser.parse_args()
    result = evaluate(args)
    write_json(args.output, result)
    for name, variant in sorted(
        result["conditions"].items(),
        key=lambda item: item[1]["panels"]["calibration"]["known_coverage"],
        reverse=True,
    )[:5]:
        print(json.dumps({"condition": name, **variant}))


if __name__ == "__main__":
    main()
