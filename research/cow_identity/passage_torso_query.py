"""Run the frozen torso-crop control against the already exposed passage regression."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from benchmark import digest, write_json
from passage_query import CachedEncoder, prepare_identifier, verify_freeze
from passage_runtime import frozen_inputs, materialize
from passage_torso import identify_whole_animals
from passage_torso_detection import observations
from smoke_runtime import CountedEncoder

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.configuration import IdentityConfig


def run_clip(clip, protocol, source, settings, catalog, encoder, gallery_cache):
    with ThreadPoolExecutor(max_workers=1) as executor:
        statuses = []
        identifier = GalleryIdentifier(
            settings,
            catalog,
            encoder,
            gallery_cache,
            executor,
            report_status=lambda event: statuses.append(event.kind),
        )
        started = time.perf_counter()
        prepare_identifier(identifier, executor)
        preparation = time.perf_counter() - started
        timeline = []
        for index, second, observation in observations(clip, source, protocol):
            identified = identify_whole_animals(identifier, clip["clip"], observation)
            timeline.append(
                {
                    "local_frame": index,
                    "second": second,
                    "width": observation.image.shape[1],
                    "height": observation.image.shape[0],
                    "boxes": [asdict(box) for box in identified.boxes],
                    "raw_detector_boxes": [asdict(box) for box in observation.boxes],
                }
            )
        if "identity_failed" in statuses:
            raise ValueError("Actual identity runtime reported a failure")
    return {
        "clip": clip["clip"],
        "gallery_preparation_seconds": preparation,
        "timeline": timeline,
        "statuses": statuses,
    }


def query(args):
    import torch

    torch.set_num_threads(2)
    freeze = verify_freeze(args)
    protocol, manifest = frozen_inputs(args.protocol)
    if args.output.exists():
        raise ValueError("Preserve the previous query outcome")
    args.output.mkdir(parents=True)
    settings = IdentityConfig(
        labels=("cow",),
        **{
            k: protocol["identity_policy"][k]
            for k in (
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
    catalog = IdentityCatalog(args.gallery)
    catalog_hash = digest(args.gallery / "catalog.json")
    clips = []
    with ExitStack() as resources:
        query_cache = EmbeddingCache(args.output / "query-embeddings.sqlite")
        resources.callback(query_cache.close)
        gallery_cache = EmbeddingCache(args.output / "gallery-embeddings.sqlite")
        resources.callback(gallery_cache.close)
        encoder = CachedEncoder(counted, query_cache)
        startup = time.perf_counter() - started
        for clip in manifest["clips"]:
            if clip["role"] != "query":
                continue
            source = materialize(clip, args.output / "clips")
            clips.append(
                run_clip(
                    clip, protocol, source, settings, catalog, encoder, gallery_cache
                )
            )
            if digest(args.gallery / "catalog.json") != catalog_hash:
                raise ValueError("Query observations changed confirmed identity labels")
    write_json(
        args.output / "predictions.json",
        {
            "freeze_sha256": digest(args.freeze),
            "protocol_sha256": digest(args.protocol),
            "encoder_fingerprint": counted.fingerprint,
            "implementation_files": freeze["files"],
            "clips": clips,
            "startup_seconds": startup,
            "total_seconds": time.perf_counter() - started,
            "new_encoded_images": counted.images,
            "new_encoder_calls": counted.calls,
            "coordinate_convention": "Original whole-visible-cow XYXY at resized1280 frame; scale back to source1920 for unchanged truth association",
            "identity_policy": "Actual GalleryIdentifier on uniquely associated torso crops carrying whole-animal trackIDs; names mapped back to original whole-animal boxes; fresh state each clip",
            "test_status": "June9 exposed regression; original failed blind control preserved separately",
        },
    )
    print(
        json.dumps(
            {
                "clips": len(clips),
                "frames": sum(len(c["timeline"]) for c in clips),
                "seconds": time.perf_counter() - started,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("freeze", "gallery", "weights", "output", "protocol"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    query(parser.parse_args())
