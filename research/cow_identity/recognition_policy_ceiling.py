"""Bound identity coverage using cached boxes and the unchanged runtime policy.

No pixels or model weights are opened. The hard ceiling counts eligible, matched
known boxes before temporal agreement. A separate idealized replay supplies a
perfect known match for each matched known box and rejects unknown/unmatched
boxes, while executing production sampling, conflict and track-state code.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from benchmark import digest, write_json

from aidetector.adapters.identity_catalog import Catalog
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    usable_crop,
)
from aidetector.configuration import IdentityConfig
from aidetector.domain.identity import choose_identity
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation

KNOWN = tuple(range(1, 7))


class OracleGallery(GalleryIdentifier):
    """Replace only gallery I/O and appearance evidence, not runtime decisions."""

    def __init__(self, settings):
        super().__init__(
            settings,
            SimpleNamespace(save_sighting=lambda *args, **kwargs: None),
            SimpleNamespace(dimension=8),
            None,
            None,
        )
        self.expected = []

    def _refresh_gallery(self):
        return Catalog(revision=1)

    def _match(self, images):
        if len(images) != len(self.expected):
            raise ValueError("Oracle evidence must follow actual sampled crop order")
        return [
            choose_identity(
                [
                    IdentityMatch(str(owner), str(owner), float(cow == owner))
                    for owner in KNOWN
                ],
                self.settings.min_similarity,
                self.settings.min_margin,
            )
            for cow in self.expected
        ]


def assess(manifest, settings):
    identifier = OracleGallery(settings)
    image = np.zeros((600, 800, 3), dtype=np.uint8)
    counts = Counter()
    per_cow = {str(cow): Counter() for cow in KNOWN}
    for frame in manifest["frames"]:
        rows = [manifest["rows"][i] for i in frame["rows"]]
        boxes = tuple(
            BoundingBox(*row["box"], "cow", row["confidence"], row["track"])
            for row in rows
        )
        eligible = [
            usable_crop(
                box, boxes, 800, 600, settings.min_crop_size, settings.max_overlap
            )
            for box in boxes
        ]
        identifier.expected = [
            row["truth"] for row, good in zip(rows, eligible, strict=True) if good
        ]
        for truth in frame["truth"]:
            if truth["cow"] in KNOWN:
                counts["visible_known"] += 1
                per_cow[str(truth["cow"])]["visible_known"] += 1
        observation = Observation(
            datetime(2026, 1, 1) + timedelta(seconds=frame["second"]),
            image,
            {"cow": 0.4},
            boxes,
        )
        result = identifier.identify("source", observation)
        for row, good, box in zip(rows, eligible, result.boxes, strict=True):
            counts["predicted_boxes"] += 1
            counts["eligible_boxes"] += good
            named = box.identity is not None and box.identity.identity_id is not None
            if row["truth"] in KNOWN:
                counts["matched_known"] += 1
                counts["eligible_known"] += good
                counts["oracle_confirmed_known"] += named
                per_cow[str(row["truth"])]["eligible_known"] += good
                per_cow[str(row["truth"])]["oracle_confirmed_known"] += named
            elif named:
                raise ValueError("The perfect-rejection control emitted a false name")
    return {
        "counts": dict(counts),
        "hard_coverage_ceiling": counts["eligible_known"] / counts["visible_known"],
        "oracle_replay_coverage": counts["oracle_confirmed_known"]
        / counts["visible_known"],
        "per_cow": {cow: dict(value) for cow, value in per_cow.items()},
    }


def run(output):
    settings = IdentityConfig(labels=("cow",))
    sources, panels = {}, {}
    for start in (930, 1230):
        path = Path(f".cache/cow-tracked-features/mixed-{start}/manifest.json")
        sources[str(path)] = digest(path)
        manifest = json.loads(path.read_text())
        if [f["second"] for f in manifest["frames"]] != list(range(start, start + 300)):
            raise ValueError("Retain every timestamp of the exposed query panel")
        panels[str(start)] = assess(manifest, settings)
    for path in (
        Path(__file__),
        Path("detector/src/aidetector/adapters/inference/identity_observations.py"),
        Path("detector/src/aidetector/domain/identity.py"),
        Path("detector/src/aidetector/domain/models.py"),
        Path("detector/src/aidetector/configuration.py"),
        Path(__file__).with_name("test_recognition_policy_ceiling.py"),
    ):
        sources[str(path)] = digest(path)
    report = {
        "scope": "Exposed 8-Calves actual mixed detector/ByteTrack queries at 1 Hz; CPU metadata only, no model inference or new pixels",
        "settings": settings.model_dump(mode="json"),
        "source_dimensions": [800, 600],
        "sources": sources,
        "panels": panels,
        "interpretation": "The hard eligible-known ceiling is independent of embeddings and already bounds all named coverage. Oracle replay executes actual sampling/conflict/agreement, but rejecting unmatched boxes may reset a physically correct track: it is an idealized labeled replay, not a tighter mathematical maximum. Gallery preparation is immediate; real initialization can only add delay.",
    }
    write_json(output, report)
    print(json.dumps(panels))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
