"""Score every independently annotated passage frame, including misses and rejects."""

import argparse
import json
from collections import Counter
from pathlib import Path

from benchmark import digest, write_json
from video_assessment import pair_boxes

from aidetector.domain.models import BoundingBox


def full_frame_boxes(frame, width, height):
    sx, sy = width / frame["width"], height / frame["height"]
    return [
        BoundingBox(box["x1"] * sx, box["y1"] * sy, box["x2"] * sx, box["y2"] * sy)
        for box in frame["boxes"]
    ]


def score_frame(
    predicted, annotation, known, width=1920, height=1080, include_uncertain=True
):
    truth = annotation["boxes"]
    matches = pair_boxes(full_frame_boxes(predicted, width, height), truth)
    considered = [row for row in truth if include_uncertain or not row["uncertain"]]
    matched_count = sum(
        include_uncertain or not truth[index]["uncertain"] for index in matches.values()
    )
    counts = Counter(
        {
            "frames": 1,
            "visible_known": sum(row["cow"] in known for row in considered),
            "visible_unknown": sum(row["cow"] not in known for row in considered),
            "uncertain_annotations": sum(row["uncertain"] for row in truth),
            "predictions": len(predicted["boxes"]),
            "matched": matched_count,
            "missed": len(considered) - matched_count,
            "correct_names": 0,
            "wrong_known_names": 0,
            "unknown_named": 0,
            "unmatched_named": 0,
            "principal_unknown_named": 0,
            "nuisance_unknown_named": 0,
        }
    )
    counts["visible_principal_unknown"] = sum(
        row["cow"] is not None
        and row["cow"] == annotation.get("principal_cow")
        and row["cow"] not in known
        for row in considered
    )
    counts["visible_nuisance_unknown"] = (
        counts["visible_unknown"] - counts["visible_principal_unknown"]
    )
    outcomes = []
    for i, box in enumerate(predicted["boxes"]):
        value = box["identity"]["identity_id"]
        name = int(value, 16) if value else None
        observed = truth[matches[i]] if i in matches else None
        category = "unnamed"
        if observed is not None and observed["uncertain"] and not include_uncertain:
            category = "uncertain_annotation_excluded"
        elif name is not None:
            if observed is None:
                category = "unmatched_named"
            elif observed["cow"] not in known:
                category = "unknown_named"
            elif name == observed["cow"]:
                category = "correct_names"
            else:
                category = "wrong_known_names"
            counts[category] += 1
            if category == "unknown_named":
                key = (
                    "principal_unknown_named"
                    if observed["cow"] is not None
                    and observed["cow"] == annotation.get("principal_cow")
                    else "nuisance_unknown_named"
                )
                counts[key] += 1
        outcomes.append(
            {
                "box": i,
                "predicted": name,
                "matched_cow": observed["cow"] if observed else None,
                "matched": observed is not None,
                "track": box["track_id"],
                "outcome": category,
            }
        )
    return counts, outcomes


def rates(counts):
    named = sum(
        counts[key]
        for key in (
            "correct_names",
            "wrong_known_names",
            "unknown_named",
            "unmatched_named",
        )
    )
    return {
        "counts": dict(counts),
        "known_coverage": counts["correct_names"] / counts["visible_known"]
        if counts["visible_known"]
        else None,
        "conservative_named_precision": counts["correct_names"] / named
        if named
        else None,
        "unknown_false_acceptance_rate": counts["unknown_named"]
        / counts["visible_unknown"]
        if counts["visible_unknown"]
        else None,
        "principal_unknown_false_acceptance_rate": counts["principal_unknown_named"]
        / counts["visible_principal_unknown"]
        if counts["visible_principal_unknown"]
        else None,
        "nuisance_unknown_false_acceptance_rate": counts["nuisance_unknown_named"]
        / counts["visible_nuisance_unknown"]
        if counts["visible_nuisance_unknown"]
        else None,
    }


def validate_prediction_timelines(predictions, clips, protocol):
    if [clip["clip"] for clip in predictions["clips"]] != list(clips):
        raise ValueError("Query predictions must retain every frozen clip in order")
    timelines = {}
    for predicted in predictions["clips"]:
        clip = clips[predicted["clip"]]
        fps = protocol.get("processing_fps", protocol["sampling_fps"])
        stride = clip["fps_numerator"] / clip["fps_denominator"] / fps
        indices = [frame["local_frame"] for frame in predicted["timeline"]]
        if not stride.is_integer() or indices != list(
            range(0, clip["frames"], int(stride))
        ):
            raise ValueError(
                "Query predictions omit, duplicate or reorder processing frames"
            )
        timelines[predicted["clip"]] = {
            frame["local_frame"]: frame for frame in predicted["timeline"]
        }
    return timelines


def count_cows(counts, frame, decisions):
    for row in frame["boxes"]:
        key = str(row["cow"]) if row["cow"] is not None else "unresolved-nuisance"
        counts.setdefault(key, Counter())["visible"] += 1
    for decision in decisions:
        if decision["matched"]:
            cow = decision["matched_cow"]
            key = str(cow) if cow is not None else "unresolved-nuisance"
            counts[key]["matched"] += 1
            counts[key][decision["outcome"]] += 1


def score(predictions, annotations, protocol, source_manifest):
    clips = {
        clip["clip"]: clip
        for clip in source_manifest["clips"]
        if clip["role"] == "query"
    }
    expected = {
        (clip["clip"], frame)
        for clip in clips.values()
        for frame in clip["sampled_local_frame_indices"]
    }
    annotation_keys = [
        (frame["clip"], frame["frame"]) for frame in annotations["frames"]
    ]
    if (
        len(annotation_keys) != len(set(annotation_keys))
        or set(annotation_keys) != expected
    ):
        raise ValueError(
            "Independent annotations must cover every frozen query frame exactly once"
        )
    timelines = validate_prediction_timelines(predictions, clips, protocol)
    known = set(protocol["known_cows"])
    overall = Counter()
    definite = Counter()
    per_clip = {}
    per_cow = {}
    outcomes = []
    for frame in sorted(
        annotations["frames"], key=lambda row: (row["clip"], row["frame"])
    ):
        clip = clips[frame["clip"]]
        predicted = timelines[frame["clip"]][frame["frame"]]
        counts, decisions = score_frame(
            predicted, frame, known, clip["width"], clip["height"]
        )
        overall.update(counts)
        definite_counts, _ = score_frame(
            predicted,
            frame,
            known,
            clip["width"],
            clip["height"],
            include_uncertain=False,
        )
        definite.update(definite_counts)
        count_cows(per_cow, frame, decisions)
        record = per_clip.setdefault(
            frame["clip"],
            {
                "counts": Counter(),
                "principal": frame["principal_cow"],
                "first_visible": None,
                "first_correct": None,
                "incorrect_samples": [],
            },
        )
        record["counts"].update(counts)
        if (
            any(row["cow"] == frame["principal_cow"] for row in frame["boxes"])
            and record["first_visible"] is None
        ):
            record["first_visible"] = frame["second"]
        if (
            any(
                item["outcome"] == "correct_names"
                and item["matched_cow"] == frame["principal_cow"]
                for item in decisions
            )
            and record["first_correct"] is None
        ):
            record["first_correct"] = frame["second"]
        if (
            counts["wrong_known_names"]
            + counts["unknown_named"]
            + counts["unmatched_named"]
        ):
            record["incorrect_samples"].append(frame["second"])
        outcomes.append(
            {
                "clip": frame["clip"],
                "frame": frame["frame"],
                "second": frame["second"],
                "decisions": decisions,
            }
        )
    return {
        "overall": rates(overall),
        "definite_annotation_sensitivity": {
            **rates(definite),
            "policy": "Diagnostic only: retain full-box association, exclude uncertain truth and its matched predictions from name metrics; every named unmatched prediction still counts as an error. Main metric retains all annotations.",
        },
        "per_cow": {cow: dict(counts) for cow, counts in per_cow.items()},
        "per_passage": {
            clip: {
                **rates(value["counts"]),
                "principal": value["principal"],
                "first_visible": value["first_visible"],
                "first_correct": value["first_correct"],
                "latency_to_correct_seconds": value["first_correct"]
                - value["first_visible"]
                if value["first_correct"] is not None
                and value["first_visible"] is not None
                else None,
                "incorrect_scored_seconds": value["incorrect_samples"],
            }
            for clip, value in per_clip.items()
        },
        "scored_timeline": outcomes,
        "limitation": "All fixed1fps annotated frames count;5fps intermediate state is causal but not independently annotated. Precision treats every named unmatched box as wrong. Intended known cows without reference photos remain in known denominator. Zero errors on this small correlated passage sample is not a reliability certification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("predictions", "annotations", "protocol", "manifest", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text())
    annotations = json.loads(args.annotations.read_text())
    if predictions["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Predictions belong to another frozen passage protocol")
    if annotations["manifest_sha256"] != digest(args.manifest):
        raise ValueError("Annotations belong to another source passage manifest")
    result = score(
        predictions,
        annotations,
        json.loads(args.protocol.read_text()),
        json.loads(args.manifest.read_text()),
    )
    result["sources"] = {
        name: {"path": str(getattr(args, name)), "sha256": digest(getattr(args, name))}
        for name in ("predictions", "annotations", "protocol", "manifest")
    }
    write_json(args.output, result)
    print(json.dumps(result["overall"]))


if __name__ == "__main__":
    main()
