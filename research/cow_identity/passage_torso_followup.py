"""Frozen border-only and border-plus-one-second continuity passage controls."""

import argparse
import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from benchmark import digest, write_json
from passage_diagnostics import cached_gallery
from passage_query import CachedEncoder
from passage_runtime import MANIFEST, sampled_frames
from passage_torso import associate_torsos, identify_whole_animals
from passage_torso_continuity import (
    BorderTorsoIdentifier,
    ObservedIdentifier,
    VisibleTrackHold,
    torso_presence,
)
from smoke_runtime import CountedEncoder

from aidetector.adapters.identity_catalog import Catalog
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation

BASE = Path(".cache/cow-passage-query-torso")
BASE_FREEZE = Path(__file__).with_name("passage_torso_query_freeze.json")
FREEZE = Path(__file__).with_name("passage_torso_followup_protocol.json")
OUTPUT = Path(".cache/cow-passage-query-torso-border")


class NoSaveCatalog:
    def save_sighting(self, *args, **kwargs):
        return None


class PreparedIdentifier(ObservedIdentifier):
    def _refresh_gallery(self):
        return Catalog()


def freeze():
    if OUTPUT.exists() or FREEZE.exists():
        raise ValueError("Preserve the previous follow-up freeze or results")
    previous = json.loads(BASE_FREEZE.read_text())
    files = dict(previous["files"])
    for path in (
        BASE_FREEZE,
        BASE / "predictions.json",
        BASE / "query-embeddings.sqlite",
        BASE / "gallery-embeddings.sqlite",
        MANIFEST,
        Path(__file__),
        Path(__file__).with_name("passage_torso_continuity.py"),
        Path(__file__).with_name("passage_diagnostics.py"),
        Path(__file__).with_name("test_passage_continuity.py"),
    ):
        files[str(path)] = digest(path)
    write_json(
        FREEZE,
        {
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "status": "Frozen research follow-up; parent authorized, shared GPU launch still coordinated separately",
            "hypothesis": "Cache-only failure audit found image-boundary rejection removes13 matched-known torso observations and resets all3 successful confirmations. No matching threshold changes.",
            "base_freeze": str(BASE_FREEZE),
            "protocol": previous["protocol"],
            "gallery": previous["gallery"],
            "annotations": previous["annotations"],
            "output": str(OUTPUT),
            "files": files,
            "arms": {
                "border_only": "Use actual GalleryIdentifier with exact original torso crop pixels, removing only image-boundary rejection through two-pixel image padding outside all crops. Keep64px, overlap.2, similarity.65, distinct-cow margin.1,3samples,.2s cadence unchanged.",
                "border_hold_1s": "Same border evidence plus causal1second maximum hold from most recent actual confirmation, only while same whole track stays visible with zero intersecting torso rectangles. Present-but-unconfirmed/ambiguous/contradictory torso clears hold. Clear on whole-track loss/reuse, gaps>1s, nonmonotonic timestamps, duplicated track IDs, or competing pending/confirmed same identities. Held names never refresh TTL. Fresh state per clip.",
            },
            "limitations": "Static gallery and fresh clip state only. Observed track loss prevents later ID reuse from inheriting a name, but a continuous tracker switch without observable loss cannot be independently detected by this hold policy.",
            "evaluation": "Score both arms once with original105-frame76-box truth and all7intended-known denominator. Preserve original failed outcome. June9 is exposed regression, not new blind testing. No parameter search or production changes. Reserved8-calves windows untouched.",
            "inference": "Reuse exact saved raw detector boxes, tracks and images. Copy old query embedding cache then fill only absent eligible-border crop hashes with same pinned official MIEW onMPS. Galleryvectors are read only from original storedJPEG cache. No YOLO retraining/rerun and no truth in matching.",
        },
    )
    print(digest(FREEZE))


def inputs():
    document = json.loads(FREEZE.read_text())
    for path, expected in document["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen follow-up input changed: {path}")
    protocol = json.loads(Path(document["protocol"]).read_text())
    previous = json.loads((BASE / "predictions.json").read_text())
    source = json.loads(MANIFEST.read_text())
    return document, protocol, previous, source


def pending_whole(raw, identifier):
    whole = tuple(box for box in raw if box.label == "whole_visible_cow")
    torsos = tuple(box for box in raw if box.label == "coat_torso")
    result = [IdentityMatch() for _ in whole]
    for index, (owner, _) in enumerate(associate_torsos(whole, torsos)):
        result[owner] = identifier.pending.get(index, IdentityMatch())
    return result


def run_clip(clip, timeline, protocol, identifier):
    path = BASE / "clips" / clip["clip"] / "source.avi"
    if digest(path) != clip["sha256"]:
        raise ValueError("Source query clip changed")
    sample = {
        **clip,
        "sampled_local_frame_indices": [frame["local_frame"] for frame in timeline],
    }
    border, hold = [], []
    wrapper = BorderTorsoIdentifier(identifier)
    continuity = VisibleTrackHold(seconds=1.0)
    for (index, image), old in zip(
        sampled_frames(sample, path, protocol["detector"]["frames_width"]),
        timeline,
        strict=True,
    ):
        if index != old["local_frame"]:
            raise ValueError("Query frame order changed")
        raw = tuple(
            BoundingBox(
                **{key: value for key, value in row.items() if key != "identity"}
            )
            for row in old["raw_detector_boxes"]
        )
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=old["second"])
        observation = Observation(at, image, {}, raw)
        result = identify_whole_animals(wrapper, clip["clip"], observation)
        held = continuity.apply(
            result, torso_presence(raw), pending_whole(raw, identifier)
        )
        border.append({**old, "boxes": [asdict(box) for box in result.boxes]})
        hold.append({**old, "boxes": [asdict(box) for box in held.boxes]})
    return border, hold


def append_panels(panels, clip_id, border, hold):
    # JSON serialization sorts object keys; arm names must not rely on that order.
    for arm, timeline in (("border_only", border), ("border_hold_1s", hold)):
        panels[arm].append({"clip": clip_id, "timeline": timeline})


def execute(weights):
    import torch

    torch.set_num_threads(2)
    document, protocol, previous, source = inputs()
    if OUTPUT.exists():
        raise ValueError("Preserve the previous follow-up output")
    OUTPUT.mkdir(parents=True)
    with (
        sqlite3.connect(
            f"file:{BASE / 'query-embeddings.sqlite'}?mode=ro", uri=True
        ) as src,
        sqlite3.connect(OUTPUT / "query-embeddings.sqlite") as dst,
    ):
        src.backup(dst)
    counted = CountedEncoder(MiewidEncoder(OUTPUT / "models", "mps", weights=weights))
    if counted.fingerprint != previous["encoder_fingerprint"]:
        raise ValueError("Follow-up encoder differs from frozen baseline")
    settings = IdentityConfig(
        labels=("cow",),
        **{
            key: protocol["identity_policy"][key]
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
    panels = {arm: [] for arm in document["arms"]}
    started = time.perf_counter()
    cache = EmbeddingCache(OUTPUT / "query-embeddings.sqlite")
    try:
        with (
            sqlite3.connect(
                f"file:{BASE / 'gallery-embeddings.sqlite'}?mode=ro", uri=True
            ) as database,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            gallery, owners = cached_gallery(
                database, counted.fingerprint, Path(document["gallery"])
            )
            encoder = CachedEncoder(counted, cache)
            for predicted in previous["clips"]:
                clip = next(
                    row for row in source["clips"] if row["clip"] == predicted["clip"]
                )
                identifier = PreparedIdentifier(
                    settings, NoSaveCatalog(), encoder, None, executor
                )
                identifier._gallery = gallery
                identifier._owners = tuple(
                    (f"{int(cow):032x}", str(cow)) for cow in owners
                )
                border, hold = run_clip(
                    clip, predicted["timeline"], protocol, identifier
                )
                append_panels(panels, clip["clip"], border, hold)
    finally:
        cache.close()
    for arm, clips in panels.items():
        result = copy.deepcopy(previous)
        result.update(
            clips=clips,
            followup_arm=arm,
            followup_freeze_sha256=digest(FREEZE),
            original_predictions_sha256=digest(BASE / "predictions.json"),
            implementation_files=document["files"],
            total_seconds=time.perf_counter() - started,
            new_encoded_images=counted.images,
            new_encoder_calls=counted.calls,
            identity_policy=document["arms"][arm],
            startup_seconds=None,
        )
        write_json(OUTPUT / f"{arm}.json", result)
    print(
        json.dumps(
            {
                "seconds": time.perf_counter() - started,
                "new_images": counted.images,
                "encoder_calls": counted.calls,
                "arms": list(panels),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    parser.add_argument("--weights", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze()
    else:
        if args.weights is None:
            parser.error("run requires --weights")
        execute(args.weights)
