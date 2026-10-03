"""Replay application photo collection from cached first-day detector proposals."""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
from benchmark import digest, write_json
from passage_query import CachedEncoder

from aidetector.adapters.identity_catalog import Catalog
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    _Track,
)
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, Observation


class EmptyHerd:
    """Capture what the real collector would offer before cows are enrolled."""

    def __init__(self):
        self.captured = []
        self.lookup = {}

    def load(self):
        return Catalog()

    def save_sighting(self, image, source, at, track_id, match, **kwargs):
        key = source, at, track_id, hashlib.sha256(image.tobytes()).hexdigest()
        self.captured.append(self.lookup[key].pop(0))
        return f"{len(self.captured):032x}"


class NoInference:
    dimension = 2152
    fingerprint = "no-model-empty-enrollment-replay"

    def encode(self, images):
        raise AssertionError(
            "An empty herd must not run inference while collecting photos"
        )


class BurstIdentifier(GalleryIdentifier):
    """Research-only first-three-samples variant; normal cadence resumes afterwards."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._capture_state = {}

    def _retain(self, source, at, track_id, candidate, match, crop, gallery_revision):
        key = source, track_id
        count, saved = self._capture_state.get(key, (0, None))
        if count < 3 or (at - saved).total_seconds() >= self.settings.review_interval:
            self.catalog.save_sighting(
                crop, source, at, track_id, match, gallery_revision=gallery_revision
            )
            count, saved = count + 1, at
            self._capture_state[key] = count, saved
        self._tracks[key] = _Track(at, candidate, match, saved)


def replay(directory, proposals, implementation, cache_path):
    catalog = EmptyHerd()
    cache = EmbeddingCache(cache_path)
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    settings = IdentityConfig(labels=("cow",), sample_interval=0.2, review_interval=30)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            identifier = implementation(
                settings, catalog, CachedEncoder(NoInference(), cache), cache, executor
            )
            for frame in proposals["frames"]:
                at = epoch + timedelta(seconds=frame["second"])
                image = cv2.imread(str(directory / frame["path"]))
                boxes = []
                for index in frame["rows"]:
                    row = proposals["rows"][index]
                    box = BoundingBox(**row["box"])
                    crop = image[box.y1 : box.y2, box.x1 : box.x2]
                    key = (
                        frame["clip"],
                        at,
                        box.track_id,
                        hashlib.sha256(crop.tobytes()).hexdigest(),
                    )
                    catalog.lookup.setdefault(key, []).append(index)
                    boxes.append(box)
                observation = Observation(at, image, {}, tuple(boxes))
                identifier.identify(frame["clip"], observation)
    finally:
        cache.close()
    return catalog.captured


def run(args):
    if not args.completed_query.exists():
        raise ValueError(
            "Keep this retention diagnostic after the frozen query outcome"
        )
    proposals = json.loads((args.proposals / "proposals.json").read_text())
    review = json.loads(args.review.read_text())
    if review["proposals_sha256"] != digest(args.proposals / "proposals.json"):
        raise ValueError("Review belongs to different first-day proposals")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panels = {}
    for name, implementation in (
        ("actual_first_then_30s", GalleryIdentifier),
        ("first_three_then_30s", BurstIdentifier),
    ):
        selected = replay(
            args.proposals,
            proposals,
            implementation,
            args.proposals / f"retention-{name}.sqlite",
        )
        accepted = [
            review["rows"][i] for i in selected if review["rows"][i]["accepted"]
        ]
        panels[name] = {
            "offered_rows": selected,
            "offered_count": len(selected),
            "review_accepted_count": len(accepted),
            "by_cow": {
                str(cow): sum(r["cow"] == cow for r in accepted)
                for cow in (2234, 2238, 5676, 5953, 6079, 6102, 6110)
            },
            "limitation": "Replays real empty-gallery collector on research torso proposals, with unknown names. Does not alter the already frozen reference gallery or test recognition accuracy.",
        }
    write_json(
        args.output,
        {
            "proposals_sha256": digest(args.proposals / "proposals.json"),
            "review_sha256": digest(args.review),
            "completed_query_sha256": digest(args.completed_query),
            "source_sha256": digest(Path(__file__)),
            "sampling_interval_seconds": 0.2,
            "detector_cadence_fps": 5,
            "scope": "Actual collection algorithm at the frozen fast-passage cadence. The current application preset's1fps detection/sample cadence is a separate baseline and is not reproduced here.",
            "panels": panels,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("proposals", "review", "completed-query", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    run(parser.parse_args())
