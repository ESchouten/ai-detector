"""Recognize cached masked animals without inheriting their initial track names.

This exposed-data diagnostic reuses production matching and temporal decisions,
but accepts isolated foreground crops without the application's rectangle-overlap
veto. It is not an execution of the complete application or a re-entry proof.
"""

import argparse
import importlib.metadata
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from cutie_appearance import read_features
from video_assessment import VideoMetrics, annotations, truth_at

from aidetector.adapters.inference.identity_observations import (
    distinct_identity_scores,
    usable_crop,
)
from aidetector.domain.identity import (
    TrackAgreement,
    choose_identity,
    reject_conflicting_matches,
)
from aidetector.domain.models import BoundingBox, IdentityMatch


def predict_panel(features, queries, owners, gallery, start, end):
    """Compare every anonymous slot with every confirmed animal, then agree.

    All reference labels come from reviewed gallery rows. Neither publisher
    labels nor the mask track's original seed name is available to this function.
    Missing or ineligible tracks lose agreement; no previous name is held.
    """
    frames = [row for row in features["frames"] if start <= row["second"] <= end]
    if [row["second"] for row in frames] != list(range(start, end + 1)):
        raise ValueError("Retain every second of the complete diagnostic panel")
    indexed = [(frame["second"], i) for frame in frames for i in frame["rows"]]
    if len({i for _, i in indexed}) != len(indexed) or any(
        type(i) is not int
        or not 0 <= i < len(features["rows"])
        or features["rows"][i]["second"] != second
        for second, i in indexed
    ):
        raise ValueError("Each crop row must belong uniquely to its recorded frame")
    agreement = TrackAgreement(min_observations=3, max_gap=5)
    previous_tracks = set()
    output = []
    for frame in frames:
        at = datetime(2026, 1, 1) + timedelta(seconds=frame["second"])
        indices = frame["rows"]
        rows = [features["rows"][i] for i in indices]
        boxes = tuple(
            BoundingBox(*row["box"], "cow", 1.0, row["track_id"]) for row in rows
        )
        current_tracks = {box.track_id for box in boxes}
        if len(current_tracks) != len(boxes) or None in current_tracks:
            raise ValueError("A frame must contain distinct anonymous object slots")
        for track in previous_tracks - current_tracks:
            agreement.update("camera", track, at, IdentityMatch())
        previous_tracks = current_tracks
        eligible = [usable_crop(box, (), 800, 600, 64, 1.0) for box in boxes]
        scores = distinct_identity_scores(queries[indices], gallery, owners)
        candidates = reject_conflicting_matches(
            [
                choose_identity(values, min_similarity=0.65, min_margin=0.10)
                if good
                else IdentityMatch()
                for values, good in zip(scores, eligible, strict=True)
            ]
        )
        named = tuple(
            replace(
                box,
                identity=agreement.update("camera", box.track_id, at, candidate),
            )
            for box, candidate in zip(boxes, candidates, strict=True)
        )
        output.append({"second": frame["second"], "boxes": named, "eligible": eligible})
    return output


def score_panel(predictions, records):
    """Score after matching is complete; retain missed and unmatched animals."""
    metrics = VideoMetrics()
    visible, correct_by_cow = Counter(), Counter()
    timeline = []
    for row in predictions:
        truth = truth_at(records, 20 * row["second"] + 1, 800, 600)
        decisions = metrics.add(row["second"], row["boxes"], truth, row["eligible"])
        visible.update(item["cow"] for item in truth)
        correct_by_cow.update(
            item["truth"] for item in decisions if item["outcome"] == "correct_name"
        )
        timeline.append({"second": row["second"], "decisions": decisions})
    counts = dict(metrics.counts)
    correct = counts["correct_name"]
    named = correct + sum(
        counts[key] for key in ("wrong_name", "unknown_named", "unmatched_named")
    )
    return {
        "counts": counts,
        "known_coverage": correct / counts["visible_known"],
        "conservative_named_precision": correct / named if named else None,
        "unknown_false_naming_rate": counts["unknown_named"]
        / counts["visible_unknown"],
        "per_cow": {
            str(cow): {
                "visible": visible[cow],
                "correctly_named": correct_by_cow[cow],
                "coverage": correct_by_cow[cow] / visible[cow],
            }
            for cow in range(1, 7)
            if visible[cow]
        },
        "confusion": dict(metrics.names),
        "timeline": timeline,
    }


def compare(protocol_path, output):
    if output.exists():
        raise FileExistsError("Preserve previous diagnostic outputs")
    protocol = json.loads(protocol_path.read_text())
    for path, expected in protocol["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen comparison input changed: {path}")
    libraries = {key: importlib.metadata.version(key) for key in protocol["libraries"]}
    if libraries != protocol["libraries"]:
        raise ValueError("Installed libraries differ from the frozen comparison")
    features, queries = read_features(Path(protocol["queries"]))
    if features["contract"]["encoder_fingerprint"] != protocol["encoder_fingerprint"]:
        raise ValueError("Query encoder differs from the selected reference encoder")
    if protocol["panels"] != [[930, 1229], [1230, 1529]]:
        raise ValueError("Only the two exposed, post-enrollment panels are supported")
    predictions = {}
    references = {}
    for name, path in protocol["galleries"].items():
        reference, gallery = read_features(Path(path))
        fingerprint = reference["contract"]["representation"]["encoder_fingerprint"]
        counts = Counter(row["cow"] for row in reference["rows"])
        if (
            fingerprint != protocol["encoder_fingerprint"]
            or gallery.shape[1] != queries.shape[1]
            or set(counts) != set(range(1, 7))
            or max(counts.values()) > 10
        ):
            raise ValueError("Gallery violates the fixed encoder or six-cow budget")
        owners = tuple((str(row["cow"]), str(row["cow"])) for row in reference["rows"])
        predictions[name] = {
            str(start): predict_panel(features, queries, owners, gallery, start, end)
            for start, end in protocol["panels"]
        }
        references[name] = dict(counts)
    # Labels enter only after every reference package's predictions are complete.
    records, _ = annotations(
        SimpleNamespace(
            annotations=Path(protocol["annotations"]),
            source_pickle=Path(protocol["source_pickle"]),
        )
    )
    report = {
        "scope": protocol["scope"],
        "protocol_sha256": digest(protocol_path),
        "libraries": libraries,
        "references_per_cow": references,
        "panels": {
            name: {key: score_panel(rows, records) for key, rows in panels.items()}
            for name, panels in predictions.items()
        },
        "limitations": [
            "Historical publisher-prompt-seeded mask geometry, not current actual-proposal initialization.",
            "Seed names never enter matching; retained anonymous masks still carry temporal information.",
            "Isolated panel replay: agreement resets even across the contiguous1229-to1230 boundary.",
            "AI-reviewed reference labels, not an independent farmer labeling study.",
            "Mask-isolated crop policy differs from the current application's overlapping-box veto.",
            "Both panels are already exposed. No cross-day, actual re-entry or held-out farm claim.",
        ],
    }
    write_json(output, report)
    print(
        json.dumps(
            {
                name: {
                    key: {
                        k: v
                        for k, v in panel.items()
                        if k not in ("timeline", "confusion")
                    }
                    for key, panel in panels.items()
                }
                for name, panels in report["panels"].items()
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    compare(arguments.protocol, arguments.output)
