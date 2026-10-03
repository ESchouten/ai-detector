"""Fixed chronological-gallery and five-second confirmation-hold comparisons."""

import argparse
import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from passage_confirmation_hold import ConfirmationHold
from passage_diagnostics import cached_gallery
from passage_query import CachedEncoder
from passage_runtime import MANIFEST, sampled_frames
from passage_torso import identify_whole_animals
from passage_torso_continuity import BorderTorsoIdentifier, torso_presence
from passage_torso_followup import (
    BASE,
    NoSaveCatalog,
    PreparedIdentifier,
    pending_whole,
)
from passage_view_gallery import OUTPUT as NEW_GALLERY
from passage_view_gallery import PROTOCOL as ENROLLMENT_PROTOCOL
from smoke_runtime import CountedEncoder

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, Observation

FREEZE = Path(__file__).with_name("passage_views_query_protocol.json")
OUTPUT = Path(".cache/cow-passage-query-views")
PREVIOUS = Path(__file__).with_name("passage_torso_followup_protocol.json")
ARMS = {
    "original_gallery_hold_5s": ("original", True),
    "chronological_gallery_border": ("chronological", False),
    "chronological_gallery_hold_5s": ("chronological", True),
}


def freeze():
    if FREEZE.exists() or OUTPUT.exists():
        raise ValueError("Preserve the previous freeze or query outcome")
    previous = json.loads(PREVIOUS.read_text())
    enrollment = json.loads(ENROLLMENT_PROTOCOL.read_text())
    files = {**previous["files"], **enrollment["files"]}
    paths = [
        PREVIOUS,
        ENROLLMENT_PROTOCOL,
        Path(__file__),
        Path(__file__).with_name("passage_confirmation_hold.py"),
        Path(__file__).with_name("test_passage_confirmation_hold.py"),
        Path(__file__).with_name("passage_view_gallery.py"),
        NEW_GALLERY / "catalog.json",
        NEW_GALLERY / "provenance.json",
        NEW_GALLERY / "confirmed-gallery.jpg",
        Path(".cache/cow-passage-query-torso-border/query-embeddings.sqlite"),
    ]
    catalog = json.loads((NEW_GALLERY / "catalog.json").read_text())
    for cow in catalog["identities"]:
        for sample in cow["samples"]:
            paths.extend(
                (
                    NEW_GALLERY / "images" / f"{sample}.jpg",
                    NEW_GALLERY / "sightings" / f"{sample}.json",
                )
            )
    provenance = json.loads((NEW_GALLERY / "provenance.json").read_text())
    paths.extend(Path(path) for path in provenance["review_sha256"])
    for path in paths:
        files[str(path)] = digest(path)
    write_json(
        FREEZE,
        {
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "status": "Fixed research controls after first-day-only independent enrollment review; no new query outcomes yet",
            "protocol": previous["protocol"],
            "annotations": previous["annotations"],
            "original_gallery": previous["gallery"],
            "new_gallery": str(NEW_GALLERY),
            "output": str(OUTPUT),
            "files": files,
            "arms": {
                key: {"gallery": gallery, "hold_5s": hold}
                for key, (gallery, hold) in ARMS.items()
            },
            "gallery_selection": "At most10 chronological June8 candidates per known passage; independent source-context identity/blur/ambiguity review, no embedding/query ranking or backfill.55accepted references,70reviewed candidates,all7known including4weakly patterned2238entry views. No external human certification.",
            "matcher": "Same official MIEW, same .65 similarity/.1margin/3samples/.2s sampling/5fps saved detections; torso border gate removed, min64px/overlap.2 unchanged. No threshold relaxation or model training.",
            "hold": "Only real3-sample confirmation refreshes5sTTL. Keep held name through weak/absent evidence on unique continuous whole track. Immediately clear on different strong pending candidate, conflicting pending/confirmed identity, observed whole-track loss/reuse, duplicate trackIDs, zero box intersection jump, nonmonotonic time or >.6s inter-frame gap. Reset actual matcher agreement before inference on unsafe continuity. No future observations; new holder per clip.",
            "limitations": "Continuous overlapping tracker identity switches are not independently observable. These are exposed June9 regressions with unchanged all-visible truth, not new blind evaluations. No production promotion implied; reserved crowded-calf windows remain unopened.",
            "evaluation": "Report all3 conditions separately against original baseline. All7known and both withheldprincipals unchanged; no selecting thresholds/gallery/model from query results.",
        },
    )
    print(digest(FREEZE))


def checked_inputs():
    document = json.loads(FREEZE.read_text())
    for path, expected in document["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen input changed:{path}")
    protocol = json.loads(Path(document["protocol"]).read_text())
    if (
        protocol["identity_policy"]["sample_interval"] != 0.2
        or protocol["processing_fps"] != 5
    ):
        raise ValueError("Temporal control requires fixed5fps/.2s distinct samples")
    return (
        document,
        protocol,
        json.loads((BASE / "predictions.json").read_text()),
        json.loads(MANIFEST.read_text()),
    )


def clip_variants(clip, timeline, protocol, identifiers):
    source = BASE / "clips" / clip["clip"] / "source.avi"
    if digest(source) != clip["sha256"]:
        raise ValueError("Frozen source clip changed")
    sample = {
        **clip,
        "sampled_local_frame_indices": [frame["local_frame"] for frame in timeline],
    }
    holders = {arm: ConfirmationHold() for arm, (_, hold) in ARMS.items() if hold}
    output = {arm: [] for arm in ARMS}
    for (index, image), frame in zip(
        sampled_frames(sample, source, 1280), timeline, strict=True
    ):
        if index != frame["local_frame"]:
            raise ValueError("Raw input frame sequence changed")
        raw = tuple(
            BoundingBox(
                **{key: value for key, value in row.items() if key != "identity"}
            )
            for row in frame["raw_detector_boxes"]
        )
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=frame["second"])
        observation = Observation(at, image, {}, raw)
        for arm, identifier in identifiers.items():
            holder = holders.get(arm)
            if holder:
                holder.before_observation(identifier, clip["clip"], observation)
            result = identify_whole_animals(
                BorderTorsoIdentifier(identifier), clip["clip"], observation
            )
            if holder:
                result = holder.apply(
                    result, torso_presence(raw), pending_whole(raw, identifier)
                )
            output[arm].append(
                {**frame, "boxes": [asdict(box) for box in result.boxes]}
            )
    return output


def prepare_galleries(document, encoder, query_cache):
    with sqlite3.connect(
        f"file:{BASE / 'gallery-embeddings.sqlite'}?mode=ro", uri=True
    ) as database:
        original = cached_gallery(
            database, encoder.fingerprint, Path(document["original_gallery"])
        )
    store = IdentityCatalog(Path(document["new_gallery"]))
    vectors, owners = [], []
    for cow in store.load().identities:
        for sample in cow.samples:
            vectors.append(query_cache.encode(encoder, [store.read_image(sample)])[0])
            owners.append(int(cow.id, 16))
    return {
        "original": original,
        "chronological": (np.stack(vectors), np.array(owners)),
    }


def execute(weights):
    import torch

    torch.set_num_threads(2)
    document, protocol, previous, source = checked_inputs()
    if OUTPUT.exists():
        raise ValueError("Preserve the existing query result")
    OUTPUT.mkdir(parents=True)
    old = Path(".cache/cow-passage-query-torso-border/query-embeddings.sqlite")
    with (
        sqlite3.connect(f"file:{old}?mode=ro", uri=True) as src,
        sqlite3.connect(OUTPUT / "embeddings.sqlite") as dst,
    ):
        src.backup(dst)
    counted = CountedEncoder(MiewidEncoder(OUTPUT / "models", "mps", weights=weights))
    if counted.fingerprint != previous["encoder_fingerprint"]:
        raise ValueError("Encoder differs from prior frozen pipeline")
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
    started = time.perf_counter()
    panels = {arm: [] for arm in ARMS}
    cache = EmbeddingCache(OUTPUT / "embeddings.sqlite")
    try:
        galleries = prepare_galleries(document, counted, cache)
        encoder = CachedEncoder(counted, cache)
        with ThreadPoolExecutor(max_workers=1) as executor:
            for predicted in previous["clips"]:
                clip = next(
                    row for row in source["clips"] if row["clip"] == predicted["clip"]
                )
                identifiers = {}
                for arm, (gallery_name, _) in ARMS.items():
                    gallery, owners = galleries[gallery_name]
                    identifier = PreparedIdentifier(
                        settings, NoSaveCatalog(), encoder, None, executor
                    )
                    identifier._gallery = gallery
                    identifier._owners = tuple(
                        (f"{int(cow):032x}", str(cow)) for cow in owners
                    )
                    identifiers[arm] = identifier
                for arm, timeline in clip_variants(
                    clip, predicted["timeline"], protocol, identifiers
                ).items():
                    panels[arm].append({"clip": clip["clip"], "timeline": timeline})
    finally:
        cache.close()
    for arm, clips in panels.items():
        result = copy.deepcopy(previous)
        result.update(
            clips=clips,
            followup_arm=arm,
            followup_freeze_sha256=digest(FREEZE),
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
