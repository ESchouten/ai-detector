"""Explain a completed torso query with immutable cached embeddings, never inference."""

import argparse
import copy
import json
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from passage_diagnostics import cached_gallery, describe_scores, truth_group, vector
from passage_metrics import full_frame_boxes, rates, score_frame
from passage_runtime import MANIFEST, sampled_frames
from passage_torso import associate_torsos, identify_whole_animals
from passage_torso_continuity import BorderTorsoIdentifier
from video_assessment import pair_boxes

from aidetector.adapters.identity_catalog import Catalog
from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, Observation

ROOT = Path(".cache/cow-passage-query-torso")
FREEZE = Path(__file__).with_name("passage_torso_query_freeze.json")
OUTPUT = Path(__file__).parent / "results/2026-10-03/purdue-torso-diagnostics.json"


class ReadOnlyEncoder:
    dimension = 2152

    def __init__(self, database, fingerprint):
        self.database, self.fingerprint = database, fingerprint
        self.images = 0

    def encode(self, images):
        self.images += len(images)
        return np.stack(
            [vector(self.database, self.fingerprint, image) for image in images]
        )


class NoSaveCatalog:
    def save_sighting(self, *args, **kwargs):
        return None


class ReplayIdentifier(GalleryIdentifier):
    """Keep the actual decision/retirement code; supply only frozen gallery vectors."""

    def _refresh_gallery(self):
        return Catalog()


def clean_box(row):
    return BoundingBox(
        **{key: value for key, value in row.items() if key != "identity"}
    )


def geometry_reason(box, boxes, image, policy):
    height, width = image.shape[:2]
    if box.x1 < 1 or box.y1 < 1 or box.x2 >= width - 1 or box.y2 >= height - 1:
        return "image_boundary"
    if min(box.x2 - box.x1, box.y2 - box.y1) < policy["min_crop_size"]:
        return "too_small"
    area = (box.x2 - box.x1) * (box.y2 - box.y1)
    for other in boxes:
        if other is box:
            continue
        overlap = max(0, min(box.x2, other.x2) - max(box.x1, other.x1)) * max(
            0, min(box.y2, other.y2) - max(box.y1, other.y1)
        )
        other_area = max(1, (other.x2 - other.x1) * (other.y2 - other.y1))
        if overlap / min(area, other_area) > policy["max_overlap"]:
            return "overlap"
    return None


def observation_stages(row, item, known):
    """Truth is used only here, after replay, to describe a scored visible animal."""
    cow = row["cow"]
    values = Counter(visible=1, known=int(cow in known))
    if item is None:
        values["missed_whole"] = 1
        return values
    values["matched_whole"] = 1
    values["associated_torso"] = int(item["associated"])
    values["eligible"] = int(item["eligible"])
    values["tracked_eligible"] = int(item["eligible"] and item["track"] is not None)
    if item["best"] is not None:
        correct = cow in known and item["best"] == cow
        values["rank1_correct"] = int(correct)
        values["rank1_wrong_or_unknown"] = int(not correct)
        values["correct_similarity_pass"] = int(correct and item["similarity_pass"])
        values["correct_margin_pass"] = int(correct and item["margin_pass"])
        values["correct_single_sample"] = int(correct and item["candidate"] == cow)
        values["correct_after_conflicts"] = int(
            correct and item["after_conflict"] == cow
        )
        if correct and item["candidate"] is None:
            reason = (
                "correct_fails_both_thresholds"
                if not item["similarity_pass"] and not item["margin_pass"]
                else "correct_fails_similarity_only"
                if not item["similarity_pass"]
                else "correct_fails_margin_only"
            )
            values[reason] = 1
    values["actual_correct_name"] = int(cow in known and item["actual"] == cow)
    values["actual_wrong_or_unknown_name"] = int(
        item["actual"] is not None and (cow not in known or item["actual"] != cow)
    )
    if item["geometry_rejection"]:
        values[f"geometry_{item['geometry_rejection']}"] = 1
    return values


def cached_frame_scores(
    frame, image, policy, database, fingerprint, gallery, owners, allow_border=False
):
    raw = tuple(clean_box(box) for box in frame["raw_detector_boxes"])
    whole = tuple(box for box in raw if box.label == "whole_visible_cow")
    torsos = tuple(box for box in raw if box.label == "coat_torso")
    pairs = associate_torsos(whole, torsos)
    associated = [box for _, box in pairs]
    scoring_image, scoring_boxes = image, associated
    if allow_border:
        scoring_image = np.pad(image, ((2, 2), (2, 2), (0, 0)), constant_values=127)
        scoring_boxes = [
            replace(box, x1=box.x1 + 2, x2=box.x2 + 2, y1=box.y1 + 2, y2=box.y2 + 2)
            for box in associated
        ]
    paired_scores = describe_scores(
        scoring_image, scoring_boxes, policy, database, fingerprint, gallery, owners
    )
    scores = [
        {
            "associated": False,
            "eligible": False,
            "best": None,
            "similarity": None,
            "margin": None,
            "candidate": None,
            "after_conflict": None,
            "similarity_pass": False,
            "margin_pass": False,
            "geometry_rejection": None,
            "track": box.track_id,
        }
        for box in whole
    ]
    counts = Counter(
        item["candidate"] for item in paired_scores if item["candidate"] is not None
    )
    for (owner, torso), item in zip(pairs, paired_scores, strict=True):
        candidate = item["candidate"]
        scores[owner].update(
            item,
            associated=True,
            geometry_rejection=None
            if item["eligible"]
            else geometry_reason(torso, associated, image, policy),
            similarity_pass=item["similarity"] is not None
            and item["similarity"] >= policy["min_similarity"],
            margin_pass=item["margin"] is not None
            and item["margin"] >= policy["min_margin"],
            after_conflict=candidate if counts[candidate] == 1 else None,
        )
    return raw, scores


def agreement_resets(previous, current, scores):
    by_track = {row["track"]: row for row in scores}
    result = []
    for key, (identity, count) in previous.items():
        now = current.get(key)
        if now is not None and now.identity_id == identity:
            continue
        item = by_track.get(key[1])
        if item is None:
            reason = "whole_track_missing"
        elif not item["associated"]:
            reason = "no_unique_torso"
        elif item["geometry_rejection"]:
            reason = item["geometry_rejection"]
        elif item["candidate"] is None:
            reason = "threshold_failure"
        elif item["after_conflict"] is None:
            reason = "duplicate_identity_conflict"
        else:
            reason = "different_candidate_or_gap"
        result.append(
            {
                "track": key[1],
                "previous_identity": int(identity, 16),
                "previous_observations": count,
                "reason": reason,
            }
        )
    return result


def replay_names(identifier, clip_id, frame, image, raw, scores, allow_border=False):
    previous = {
        key: (state.identity_id, state.observations)
        for key, state in identifier.agreement._tracks.items()
    }
    at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=frame["second"])
    replay = identify_whole_animals(
        BorderTorsoIdentifier(identifier) if allow_border else identifier,
        clip_id,
        Observation(at, image, {}, raw),
    )
    for box, original, item in zip(replay.boxes, frame["boxes"], scores, strict=True):
        if box.identity.identity_id != original["identity"]["identity_id"]:
            raise ValueError(
                f"Actual runtime replay differs: {clip_id} frame{frame['local_frame']}"
            )
        item["actual"] = (
            int(box.identity.identity_id, 16) if box.identity.identity_id else None
        )
        agreement = identifier.agreement._tracks.get((clip_id, box.track_id))
        item["agreement_observations"] = agreement.observations if agreement else 0
    return agreement_resets(previous, identifier.agreement._tracks, scores)


def score_annotation(
    clip, frame, scores, annotation, known, stages, groups, per_cow, per_clip
):
    matched_truth = []
    if annotation is not None:
        matches = pair_boxes(
            full_frame_boxes(frame, clip["width"], clip["height"]),
            annotation["boxes"],
        )
        reverse = {j: i for i, j in matches.items()}
        for j, row in enumerate(annotation["boxes"]):
            i = reverse.get(j)
            item = scores[i] if i is not None else None
            values = observation_stages(row, item, known)
            group = truth_group(row, annotation["principal_cow"])
            groups.setdefault(group, Counter()).update(values)
            cow_key = str(row["cow"]) if row["cow"] is not None else "nuisance"
            per_cow.setdefault(cow_key, Counter()).update(values)
            per_clip.setdefault(clip["clip"], Counter()).update(values)
            matched_truth.append(
                {
                    "cow": row["cow"],
                    "group": group,
                    "prediction_index": i,
                    "stages": dict(values),
                }
            )
        for stage, field in (
            ("eligible_rank1", "best"),
            ("single_observation_threshold", "candidate"),
            ("after_duplicate_conflicts", "after_conflict"),
            ("actual_three_observation_policy", "actual"),
        ):
            variant = copy.deepcopy(frame)
            for box, item in zip(variant["boxes"], scores, strict=True):
                name = item[field]
                box["identity"]["identity_id"] = (
                    f"{name:032x}" if name is not None else None
                )
            counts, _ = score_frame(variant, annotation, known)
            stages[stage].update(counts)
    return matched_truth


def diagnostic_paths(allow_border, chronological):
    query_root = Path(".cache/cow-passage-query-torso-border") if allow_border else ROOT
    prediction_path = query_root / (
        "border_only.json" if allow_border else "predictions.json"
    )
    output = (
        OUTPUT.with_name("purdue-torso-border-diagnostics.json")
        if allow_border
        else OUTPUT
    )
    gallery_path = Path(".cache/cow-passage-gallery-torso")
    query_database = query_root / "query-embeddings.sqlite"
    gallery_database_path = ROOT / "gallery-embeddings.sqlite"
    followup_protocol = Path(__file__).with_name("passage_torso_followup_protocol.json")
    if chronological:
        query_root = Path(".cache/cow-passage-query-views")
        prediction_path = query_root / "chronological_gallery_border.json"
        output = OUTPUT.with_name("purdue-views-chronological-diagnostics.json")
        gallery_path = Path(".cache/cow-passage-gallery-views")
        query_database = gallery_database_path = query_root / "embeddings.sqlite"
        followup_protocol = Path(__file__).with_name(
            "passage_views_query_protocol.json"
        )
    return (
        prediction_path,
        output,
        gallery_path,
        query_database,
        gallery_database_path,
        followup_protocol,
    )


def run(allow_border=False, chronological=False):
    (
        prediction_path,
        output,
        gallery_path,
        query_database,
        gallery_database_path,
        followup_protocol,
    ) = diagnostic_paths(allow_border, chronological)
    freeze = json.loads(FREEZE.read_text())
    protocol_path = Path(freeze["protocol"])
    protocol = json.loads(protocol_path.read_text())
    predictions = json.loads(prediction_path.read_text())
    annotations_path = Path(freeze["annotations"])
    annotations = json.loads(annotations_path.read_text())
    source = json.loads(MANIFEST.read_text())
    if predictions["freeze_sha256"] != digest(FREEZE) or predictions[
        "protocol_sha256"
    ] != digest(protocol_path):
        raise ValueError("Frozen query/protocol mismatch")
    if annotations["manifest_sha256"] != digest(MANIFEST):
        raise ValueError("Independent annotation source changed")
    if allow_border and predictions["followup_freeze_sha256"] != digest(
        followup_protocol
    ):
        raise ValueError("Border predictions belong to another follow-up freeze")
    known = set(protocol["known_cows"])
    policy = protocol["identity_policy"]
    settings = IdentityConfig(
        labels=("cow",),
        **{
            key: policy[key]
            for key in (
                "min_similarity",
                "min_margin",
                "min_observations",
                "sample_interval",
                "min_crop_size",
                "max_overlap",
            )
        },
    )
    fingerprint = predictions["encoder_fingerprint"]
    truth = {(row["clip"], row["frame"]): row for row in annotations["frames"]}
    stages = {
        key: Counter()
        for key in (
            "eligible_rank1",
            "single_observation_threshold",
            "after_duplicate_conflicts",
            "actual_three_observation_policy",
        )
    }
    groups, per_cow, per_clip = {}, {}, {}
    overall, timeline = Counter(), []
    with (
        sqlite3.connect(f"file:{query_database}?mode=ro", uri=True) as database,
        sqlite3.connect(
            f"file:{gallery_database_path}?mode=ro", uri=True
        ) as gallery_database,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        gallery, owners = cached_gallery(gallery_database, fingerprint, gallery_path)
        encoder = ReadOnlyEncoder(database, fingerprint)
        for predicted_clip in predictions["clips"]:
            clip = next(
                row for row in source["clips"] if row["clip"] == predicted_clip["clip"]
            )
            sample = {
                **clip,
                "sampled_local_frame_indices": [
                    frame["local_frame"] for frame in predicted_clip["timeline"]
                ],
            }
            path = ROOT / "clips" / clip["clip"] / "source.avi"
            if digest(path) != clip["sha256"]:
                raise ValueError("Frozen query video changed")
            identifier = ReplayIdentifier(
                settings, NoSaveCatalog(), encoder, None, executor
            )
            identifier._gallery = gallery
            identifier._owners = tuple((f"{int(cow):032x}", str(cow)) for cow in owners)
            for (index, image), frame in zip(
                sampled_frames(sample, path, protocol["detector"]["frames_width"]),
                predicted_clip["timeline"],
                strict=True,
            ):
                raw, scores = cached_frame_scores(
                    frame,
                    image,
                    policy,
                    database,
                    fingerprint,
                    gallery,
                    owners,
                    allow_border,
                )
                resets = replay_names(
                    identifier, clip["clip"], frame, image, raw, scores, allow_border
                )
                overall.update(
                    {
                        "processing_frames": 1,
                        "whole_boxes": len(scores),
                        "raw_torso_boxes": sum(
                            box.label == "coat_torso" for box in raw
                        ),
                        "unique_torso_associations": sum(
                            item["associated"] for item in scores
                        ),
                        "eligible_torsos": sum(item["eligible"] for item in scores),
                        "threshold_candidates": sum(
                            item["candidate"] is not None for item in scores
                        ),
                        "post_conflict_candidates": sum(
                            item["after_conflict"] is not None for item in scores
                        ),
                        "actual_names": sum(
                            item["actual"] is not None for item in scores
                        ),
                    }
                )
                annotation = truth.get((clip["clip"], index))
                matched_truth = score_annotation(
                    clip,
                    frame,
                    scores,
                    annotation,
                    known,
                    stages,
                    groups,
                    per_cow,
                    per_clip,
                )
                timeline.append(
                    {
                        "clip": clip["clip"],
                        "frame": index,
                        "second": frame["second"],
                        "scored": annotation is not None,
                        "whole_boxes": frame["boxes"],
                        "scores": scores,
                        "matched_truth": matched_truth,
                        "agreement_resets": resets,
                    }
                )
    result = {
        "status": "Post-result cache-only causal diagnostic. No inference, threshold fitting or changes to the frozen query outcome.",
        "freeze_sha256": digest(followup_protocol if allow_border else FREEZE),
        "original_freeze_sha256": digest(FREEZE),
        "predictions_sha256": digest(prediction_path),
        "allow_border": allow_border,
        "chronological_gallery": chronological,
        "annotations_sha256": digest(annotations_path),
        "source_sha256": digest(Path(__file__)),
        "replay": "Actual GalleryIdentifier and TrackAgreement decision code, frozen prepared gallery, read-only cache-only encoder, no catalog writes. Every output identity agrees with all508 frozen processing frames; a cache miss or mismatch fails the diagnostic.",
        "replayed_cached_images": encoder.images,
        "processing_counts": dict(overall),
        "agreement_reset_counts": dict(
            Counter(
                event["reason"]
                for frame in timeline
                for event in frame["agreement_resets"]
            )
        ),
        "scored_stages": {key: rates(value) for key, value in stages.items()},
        "annotation_groups": {key: dict(value) for key, value in groups.items()},
        "per_cow": {key: dict(value) for key, value in per_cow.items()},
        "per_clip": {key: dict(value) for key, value in per_clip.items()},
        "limitations": [
            "Stage rank1 and single-sample outputs are diagnostic ablations, not new accepted runtime policies.",
            "Every intended known observation remains in denominator regardless of enrollment coverage. Ground truth appears only after cached production predictions.",
            "Annotations are AI-assisted review. June9 remains exposed regression, not a new blind test. No reserved crowded-calf frames used.",
        ],
        "timeline": timeline,
    }
    write_json(output, result)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ("timeline", "per_clip")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-border", action="store_true")
    parser.add_argument("--chronological-gallery", action="store_true")
    args = parser.parse_args()
    run(args.allow_border or args.chronological_gallery, args.chronological_gallery)
