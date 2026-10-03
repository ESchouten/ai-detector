"""Frozen geometric coat matching on the unchanged public passage pipeline."""

import argparse
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
from benchmark import digest, write_json
from local_features import CONTRACT
from passage_confirmation_hold import ConfirmationHold
from passage_local_match import MIN_INLIERS, MIN_MARGIN, LocalMatcher, select
from passage_runtime import MANIFEST, sampled_frames
from passage_torso import identify_whole_animals
from passage_torso_continuity import BorderTorsoIdentifier, torso_presence
from passage_torso_followup import (
    BASE,
    NoSaveCatalog,
    PreparedIdentifier,
    pending_whole,
)
from passage_views_query import FREEZE as PREVIOUS

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, Observation

FREEZE = Path(__file__).with_name("passage_local_protocol.json")
OUTPUT = Path(".cache/cow-passage-local")
ARMS = {"local_border": False, "local_hold_5s": True}


class NoEncoder:
    dimension = 1

    def encode(self, images):
        raise AssertionError("The RootSIFT control must not invoke a neural encoder")


class LocalIdentifier(PreparedIdentifier):
    def __init__(self, settings, matcher, executor):
        super().__init__(settings, NoSaveCatalog(), NoEncoder(), None, executor)
        self.matcher = matcher

    def _match(self, images):
        self.last_scores = [self.matcher.score(image) for image in images]
        return [select(row["ranked"]) for row in self.last_scores]


def freeze():
    if FREEZE.exists() or OUTPUT.exists():
        raise ValueError("Preserve prior protocol and outcomes")
    previous = json.loads(PREVIOUS.read_text())
    files = dict(previous["files"])
    for path in (
        PREVIOUS,
        Path(__file__),
        Path(__file__).with_name("passage_local_match.py"),
        Path(__file__).with_name("local_features.py"),
        Path(__file__).with_name("test_passage_local.py"),
    ):
        files[str(path)] = digest(path)
    write_json(
        FREEZE,
        {
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "protocol": previous["protocol"],
            "annotations": previous["annotations"],
            "gallery": previous["new_gallery"],
            "files": files,
            "output": str(OUTPUT),
            "extractor": CONTRACT,
            "fixed_match": {
                "minimum_inliers": MIN_INLIERS,
                "minimum_distinct_identity_margin": MIN_MARGIN,
                "selection": "Established independent calf-development rule, not selected on Purdue scores. Max geometric inliers per cow across unchanged55June8reviewedJPEGs. No fusion or query threshold grid.",
            },
            "arms": ARMS,
            "temporal": previous["hold"],
            "background": "Tight predicted coat torsos and existing centered ellipse suppress crop edges. Distinct-cow gallery references from the same camera compete under the fixed margin. These do NOT guarantee background exclusion. Retain best-pair inlier coordinates, hull coverage and query pixels for each cow and report unknown mistakes. Do not reinterpret background matches as valid coat evidence.",
            "unchanged": "Original saved whole boxes and tracks, min64px/overlap.2,3distinctsamples/.2s at5fps, border wrapper, temporal reset/conflicts, same all105frames/76truthboxes including46known,10withheldprincipal,20nuisance. Static55refs/no new labeling. No source filenames or query truth enter matcher.",
            "scope": "CPU2threads research control; exposed June9 regression, not new blind test. No production edits. Reserved calf windows untouched.",
        },
    )
    print(digest(FREEZE))


def clip_predictions(clip, frames, identifiers):
    path = BASE / "clips" / clip["clip"] / "source.avi"
    if digest(path) != clip["sha256"]:
        raise ValueError("Source clip differs from frozen manifest")
    sample = {**clip, "sampled_local_frame_indices": [f["local_frame"] for f in frames]}
    holders = {arm: ConfirmationHold() for arm, hold in ARMS.items() if hold}
    output = {arm: [] for arm in ARMS}
    for (index, image), old in zip(
        sampled_frames(sample, path, 1280), frames, strict=True
    ):
        if index != old["local_frame"]:
            raise ValueError("Query chronology differs from frozen baseline")
        raw = tuple(
            BoundingBox(**{k: v for k, v in row.items() if k != "identity"})
            for row in old["raw_detector_boxes"]
        )
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=old["second"])
        observation = Observation(at, image, {}, raw)
        for arm, identifier in identifiers.items():
            holder = holders.get(arm)
            if holder:
                holder.before_observation(identifier, clip["clip"], observation)
            identifier.last_scores = []
            result = identify_whole_animals(
                BorderTorsoIdentifier(identifier), clip["clip"], observation
            )
            if holder:
                result = holder.apply(
                    result, torso_presence(raw), pending_whole(raw, identifier)
                )
            output[arm].append(
                {
                    **old,
                    "boxes": [asdict(box) for box in result.boxes],
                    "local_crops": [
                        row["pixels_sha256"] for row in identifier.last_scores
                    ],
                }
            )
    return output


def execute():
    cv2.setNumThreads(2)
    document = json.loads(FREEZE.read_text())
    for path, expected in document["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen input changed:{path}")
    if OUTPUT.exists():
        raise ValueError("Preserve existing result")
    protocol = json.loads(Path(document["protocol"]).read_text())
    if (
        protocol["processing_fps"] != 5
        or protocol["identity_policy"]["sample_interval"] != 0.2
    ):
        raise ValueError("This control requires fixed5fps/.2s cadence")
    original = json.loads((BASE / "predictions.json").read_text())
    source = json.loads(MANIFEST.read_text())
    settings = IdentityConfig(
        labels=("cow",),
        **{
            key: protocol["identity_policy"][key]
            for key in (
                "min_observations",
                "sample_interval",
                "min_crop_size",
                "max_overlap",
            )
        },
    )
    started = time.perf_counter()
    matcher = LocalMatcher(
        IdentityCatalog(Path(document["gallery"])), OUTPUT / "features"
    )
    panels = {arm: [] for arm in ARMS}
    with ThreadPoolExecutor(max_workers=1) as executor:
        for predicted in original["clips"]:
            clip = next(
                row for row in source["clips"] if row["clip"] == predicted["clip"]
            )
            identifiers = {
                arm: LocalIdentifier(settings, matcher, executor) for arm in ARMS
            }
            for arm, timeline in clip_predictions(
                clip, predicted["timeline"], identifiers
            ).items():
                panels[arm].append({"clip": clip["clip"], "timeline": timeline})
            print(
                json.dumps(
                    {"completed_clip": clip["clip"], "crops": len(matcher.observed)}
                ),
                flush=True,
            )
    seconds = time.perf_counter() - started
    for arm, clips in panels.items():
        result = copy.deepcopy(original)
        result.update(
            clips=clips,
            followup_arm=arm,
            followup_freeze_sha256=digest(FREEZE),
            encoder_fingerprint=None,
            local_fingerprint=matcher.fingerprint,
            identity_policy=document["fixed_match"],
            total_seconds=seconds,
            implementation_files=document["files"],
            startup_seconds=None,
        )
        write_json(OUTPUT / f"{arm}.json", result)
    write_json(
        OUTPUT / "evidence.json",
        {
            "protocol_sha256": digest(FREEZE),
            "contract": matcher.contract,
            "fingerprint": matcher.fingerprint,
            "query_crops": matcher.observed,
            "total_seconds": seconds,
        },
    )
    print(json.dumps({"seconds": seconds, "crops": len(matcher.observed)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    args = parser.parse_args()
    freeze() if args.action == "freeze" else execute()
