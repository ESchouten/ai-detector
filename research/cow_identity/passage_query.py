"""Run the frozen production passage policy after independent truth is sealed."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from passage_runtime import PROTOCOL, detector_observations, frozen_inputs, materialize
from smoke_runtime import CountedEncoder
from video_assessment import pixels_hash

from aidetector.adapters.identity_catalog import (
    Catalog,
    EnrolledIdentity,
    IdentityCatalog,
)
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import IdentityMatch, Observation


class CachedEncoder:
    """Cache actual pixels only; labels, track IDs and filenames never enter keys."""

    def __init__(self, encoder, cache):
        self.encoder, self.cache = encoder, cache
        self.fingerprint, self.dimension = encoder.fingerprint, encoder.dimension

    def encode(self, images):
        return self.cache.encode(self.encoder, images)


def diverse_references(indices, vectors, maximum):
    if not indices:
        return []
    similarity = vectors[indices] @ vectors[indices].T
    selected = [int(np.argmax(similarity.mean(axis=1)))]
    while len(selected) < min(maximum, len(indices)):
        nearest = similarity[:, selected].max(axis=1)
        nearest[selected] = np.inf
        selected.append(int(np.argmin(nearest)))
    return [indices[i] for i in selected]


def save_references(catalog, proposals, selected, directory):
    samples = []
    for index in selected:
        row = proposals["rows"][index]
        if not row["eligible"]:
            raise ValueError("Reviewed reference failed production crop eligibility")
        crop = cv2.imread(str(directory / row["path"]))
        if crop is None or pixels_hash(crop) != row["pixels_sha256"]:
            raise ValueError("Confirmed reference pixels changed")
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=row["second"])
        sample = catalog.save_sighting(
            crop, row["clip"], at, row["box"]["track_id"], IdentityMatch()
        )
        if sample is None:
            raise ValueError("Reference could not be retained")
        samples.append(sample)
    return tuple(samples)


def seed_confirmed_gallery(args):
    protocol, _ = frozen_inputs(args.protocol)
    proposals = json.loads((args.proposals / "proposals.json").read_text())
    if proposals["protocol_sha256"] != digest(args.protocol):
        raise ValueError("Enrollment proposals belong to another frozen protocol")
    review = json.loads(args.review.read_text())
    if review["proposals_sha256"] != digest(args.proposals / "proposals.json"):
        raise ValueError("Enrollment review belongs to other proposals")
    if digest(args.proposals / "vectors.npz") != proposals["vectors_sha256"]:
        raise ValueError("Enrollment selection vectors changed")
    if [item["row"] for item in review["rows"]] != list(range(len(proposals["rows"]))):
        raise ValueError("Every proposed crop needs an explicit review outcome")
    if (args.output / "catalog.json").exists():
        raise ValueError("Preserve the already seeded immutable gallery")
    with np.load(args.proposals / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    catalog = IdentityCatalog(args.output)
    identities, selected_rows = [], {}
    for cow in protocol["known_cows"]:
        eligible = [
            item["row"]
            for item in review["rows"]
            if item["accepted"] and item["cow"] == cow
        ]
        selected = diverse_references(
            eligible, vectors, protocol["enrollment"]["maximum_references_per_cow"]
        )
        samples = save_references(catalog, proposals, selected, args.proposals)
        identities.append(
            EnrolledIdentity(id=f"{cow:032x}", name=str(cow), samples=tuple(samples))
        )
        selected_rows[str(cow)] = selected
    accepted = [item for item in review["rows"] if item["accepted"]]
    if any(item["cow"] not in protocol["known_cows"] for item in accepted):
        raise ValueError("Unenrolled identities cannot supply reference photos")
    document = Catalog(revision=1, identities=tuple(identities))
    (args.output / "catalog.json").write_text(document.model_dump_json(indent=2))
    write_json(
        args.output / "provenance.json",
        {
            "protocol_sha256": digest(args.protocol),
            "review_sha256": digest(args.review),
            "proposals_sha256": digest(args.proposals / "proposals.json"),
            "catalog_sha256": digest(args.output / "catalog.json"),
            "selected_rows": selected_rows,
            "reference_files": {
                sample: digest(args.output / "images" / f"{sample}.jpg")
                for cow in identities
                for sample in cow.samples
            },
            "reference_metadata": {
                sample: digest(args.output / "sightings" / f"{sample}.json")
                for cow in identities
                for sample in cow.samples
            },
            "missing_enrollment_counts_as_known_coverage_failure": True,
        },
    )
    print(
        json.dumps(
            {
                "references": sum(len(cow.samples) for cow in identities),
                "known_cows": len(identities),
                "cows_with_references": sum(bool(cow.samples) for cow in identities),
            }
        )
    )


def prepare_identifier(identifier, executor):
    """Finish the actual asynchronous preparation before any scored observation."""
    empty = Observation(
        datetime(1999, 1, 1, tzinfo=UTC), np.zeros((2, 2, 3), np.uint8), {}
    )
    identifier.identify("unscored-gallery-preparation", empty)
    executor.submit(lambda: None).result()
    identifier.identify("unscored-gallery-preparation", empty)
    if identifier._prepared_catalog != identifier.catalog.load():
        raise ValueError("Production gallery did not become ready")


def verify_freeze(args):
    freeze = json.loads(args.freeze.read_text())
    if (
        freeze["status"]
        != "Approved frozen query run; independent exhaustive annotations complete"
    ):
        raise ValueError(
            "Query inference has not been approved after annotation freeze"
        )
    for path, expected in freeze["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen query input changed: {path}")
    if (
        freeze["gallery"] != str(args.gallery)
        or freeze["output"] != str(args.output)
        or freeze["protocol"] != str(args.protocol)
    ):
        raise ValueError("Query output or gallery differs from the frozen run")
    return freeze


def query(args):
    freeze = verify_freeze(args)
    protocol, manifest = frozen_inputs(args.protocol)
    if args.output.exists():
        raise ValueError("Use the fresh frozen query output directory")
    args.output.mkdir(parents=True)
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
    counted = CountedEncoder(
        MiewidEncoder(args.output / "models", "mps", weights=args.weights)
    )
    query_cache = EmbeddingCache(args.output / "query-embeddings.sqlite")
    gallery_cache = EmbeddingCache(args.output / "gallery-embeddings.sqlite")
    encoder = CachedEncoder(counted, query_cache)
    catalog = IdentityCatalog(args.gallery)
    catalog_hash = digest(args.gallery / "catalog.json")
    clips = []
    startup = time.perf_counter() - started
    try:
        for clip in manifest["clips"]:
            if clip["role"] != "query":
                continue
            source = materialize(clip, args.output / "clips")
            with ThreadPoolExecutor(max_workers=1) as executor:
                statuses = []
                identifier = GalleryIdentifier(
                    settings,
                    catalog,
                    encoder,
                    gallery_cache,
                    executor,
                    report_status=lambda event, statuses=statuses: statuses.append(
                        event.kind
                    ),
                )
                preparation = time.perf_counter()
                prepare_identifier(identifier, executor)
                preparation = time.perf_counter() - preparation
                timeline = []
                for index, second, observation in detector_observations(
                    clip, source, protocol
                ):
                    identified = identifier.identify(clip["clip"], observation)
                    if any(box.identity is None for box in identified.boxes):
                        raise ValueError("Actual identifier omitted identity result")
                    timeline.append(
                        {
                            "local_frame": index,
                            "second": second,
                            "width": observation.image.shape[1],
                            "height": observation.image.shape[0],
                            "boxes": [asdict(box) for box in identified.boxes],
                        }
                    )
                if "identity_failed" in statuses:
                    raise ValueError("Actual identity runtime reported a failure")
                clips.append(
                    {
                        "clip": clip["clip"],
                        "gallery_preparation_seconds": preparation,
                        "timeline": timeline,
                        "statuses": statuses,
                    }
                )
            if digest(args.gallery / "catalog.json") != catalog_hash:
                raise ValueError("Query observations changed confirmed identity labels")
    finally:
        query_cache.close()
        gallery_cache.close()
    write_json(
        args.output / "predictions.json",
        {
            "freeze_sha256": digest(args.freeze),
            "protocol_sha256": digest(args.protocol),
            "encoder_fingerprint": encoder.fingerprint,
            "implementation_files": freeze["files"],
            "clips": clips,
            "startup_seconds": startup,
            "total_seconds": time.perf_counter() - started,
            "new_encoded_images": counted.images,
            "new_encoder_calls": counted.calls,
            "coordinate_convention": "Box XYXY in resized full frame; evaluation scales each axis back to source width1920/height1080 before association",
            "identity_policy": "Unmodified production GalleryIdentifier; fresh temporal state and detector per clip; gallery prewarmed; all sampled frames retained including empty/rejected outputs",
        },
    )
    print(
        json.dumps(
            {
                "clips": len(clips),
                "frames": sum(len(clip["timeline"]) for clip in clips),
                "named": sum(
                    bool(box["identity"]["identity_id"])
                    for clip in clips
                    for frame in clip["timeline"]
                    for box in frame["boxes"]
                ),
                "seconds": time.perf_counter() - started,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("seed-gallery")
    for name in ("proposals", "review", "output"):
        enroll.add_argument(f"--{name}", type=Path, required=True)
    enroll.add_argument("--protocol", type=Path, default=PROTOCOL)
    run = commands.add_parser("query")
    for name in ("freeze", "gallery", "weights", "output"):
        run.add_argument(f"--{name}", type=Path, required=True)
    run.add_argument("--protocol", type=Path, default=PROTOCOL)
    args = parser.parse_args()
    seed_confirmed_gallery(args) if args.command == "seed-gallery" else query(args)


if __name__ == "__main__":
    main()
