"""Bounded public-video smoke of the real identity adapters, cache and live output.

This is a same-clip integration check, not a cattle recognition accuracy study.
No private streams, external AI services or unknown pickle code are used.
"""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json

from aidetector.adapters.identity_catalog import (
    Catalog,
    EnrolledIdentity,
    IdentityCatalog,
)
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.adapters.inference.yolo import map_observations
from aidetector.adapters.live_preview import LivePreview
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import Frame, IdentityMatch


class CountedEncoder:
    def __init__(self, encoder):
        self.encoder = encoder
        self.dimension = encoder.dimension
        self.fingerprint = encoder.fingerprint
        self.calls = 0
        self.images = 0

    def encode(self, images):
        self.calls += 1
        self.images += len(images)
        return self.encoder.encode(images)


def annotated_crops(annotations: Path, source_pickle: Path, frame: np.ndarray):
    """Read the existing safe numeric conversion and verify its publisher source."""
    with np.load(annotations, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata_json"]))
        if digest(source_pickle) != metadata["source_sha256"]:
            raise ValueError(
                "Safe annotations do not match the original publisher file"
            )
        if metadata["coordinate_convention"] != "normalized-center-width-height":
            raise ValueError("Unexpected annotation coordinates")
        height, width = frame.shape[:2]
        crops = {}
        for cow in (1, 3):
            selected = np.flatnonzero((data["frame_id"] == 1) & (data["cow_id"] == cow))
            if len(selected) != 1:
                raise ValueError(
                    f"Publisher frame 1 needs exactly one annotation for calf {cow}"
                )
            i = selected[0]
            x, y, w, h = (
                float(data[key][i])
                for key in ("x_center", "y_center", "width", "height")
            )
            x1, y1 = max(0, int((x - w / 2) * width)), max(0, int((y - h / 2) * height))
            x2, y2 = (
                min(width, int((x + w / 2) * width)),
                min(height, int((y + h / 2) * height)),
            )
            crops[cow] = frame[y1:y2, x1:x2].copy()
    return crops, metadata


def parity(encoder, weights: Path, crops: list[np.ndarray], device: str):
    from comparison_encoders import ComparisonEncoder

    control = ComparisonEncoder("miewid", weights, device)
    expected, actual = control.encode(crops), encoder.encode(crops)
    np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=2e-4)
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1, atol=2e-5)
    if actual.shape != (len(crops), 2152) or not np.isfinite(actual).all():
        raise AssertionError(
            "Production identity embeddings have invalid shape or values"
        )
    return {
        "crops": len(crops),
        "dimension": 2152,
        "maximum_absolute_difference": float(np.abs(actual - expected).max()),
        "minimum_cosine": float(np.sum(actual * expected, axis=1).min()),
    }


def seed_gallery(catalog: IdentityCatalog, crops: dict[int, np.ndarray], at: datetime):
    identities = []
    for cow, image in crops.items():
        sample = catalog.save_sighting(
            image, "publisher-first-frame", at, None, IdentityMatch()
        )
        if sample is None:
            raise AssertionError("Enrollment sample was not retained")
        identities.append(
            EnrolledIdentity(
                id=f"{cow:032x}", name=f"Dataset calf {cow}", samples=(sample,)
            )
        )
    document = Catalog(revision=1, identities=tuple(identities))
    (catalog.directory / "catalog.json").write_text(document.model_dump_json(indent=2))
    return document


def await_preview(path: Path, captured_at: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            document = json.loads(path.read_text())
            if document["capturedAt"] == captured_at:
                return document
        time.sleep(0.01)
    raise TimeoutError("Live preview did not publish the final observation")


def collect_video(capture, args, catalog, crops, identifier, detector):
    fps = capture.get(cv2.CAP_PROP_FPS)
    cow_classes = [key for key, name in detector.names.items() if name == "cow"]
    if len(cow_classes) != 1:
        raise ValueError("Smoke detector must have one cow class")
    classes = {cow_classes[0]: ("cow", 0.25)}
    source = "public-8-calves-offline"
    source_key = hashlib.sha256(source.encode()).hexdigest()
    preview = LivePreview(args.output / "live", interval=0.01)
    publish = preview.observer("detector-1", (source,))
    leases = args.output / "live" / "leases"
    leases.mkdir(parents=True)
    base_time = datetime(
        2000, 1, 1, tzinfo=UTC
    )  # Synthetic observation clock, not capture date.
    counts = {
        "frames": 0,
        "boxes": 0,
        "tracked_boxes": 0,
        "identified_boxes": 0,
        "unknown_boxes": 0,
        "empty_gallery_sightings": 0,
    }
    timeline = []
    document = None
    with preview.open():
        for second in range(args.seconds):
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(second * fps))
            ok, image = capture.read()
            if not ok:
                raise ValueError(f"Video ended before second {second}")
            at = base_time + timedelta(seconds=second)
            if second == 3:
                counts["empty_gallery_sightings"] = len(
                    list((catalog.directory / "sightings").glob("*.json"))
                )
                if not counts["empty_gallery_sightings"]:
                    raise AssertionError(
                        "Empty-gallery mode did not retain any real cow crops"
                    )
                document = seed_gallery(catalog, crops, base_time)
            result = detector.track(
                image,
                persist=True,
                tracker="bytetrack.yaml",
                device=args.device,
                classes=cow_classes,
                conf=0.25,
                imgsz=640,
                quantize=32,
                verbose=False,
            )[0]
            observation = map_observations(result, (Frame(at, image),), classes)[0]
            identified = identifier.identify(source, observation)
            for before, after in zip(observation.boxes, identified.boxes, strict=True):
                if (before.x1, before.y1, before.x2, before.y2) != (
                    after.x1,
                    after.y1,
                    after.x2,
                    after.y2,
                ):
                    raise AssertionError(
                        "Identity processing changed detector box coordinates"
                    )
                if after.identity is None:
                    raise AssertionError("Cow box omitted its identity result")
            counts["frames"] += 1
            counts["boxes"] += len(identified.boxes)
            counts["tracked_boxes"] += sum(
                box.track_id is not None for box in identified.boxes
            )
            named = sum(bool(box.identity.identity_id) for box in identified.boxes)
            counts["identified_boxes"] += named
            counts["unknown_boxes"] += len(identified.boxes) - named
            timeline.append(
                {"second": second, "boxes": len(identified.boxes), "named": named}
            )
            write_json(
                leases / f"{source_key}.json",
                {"version": 1, "expiresAt": time.time() + 20},
            )
            publish(source, identified)
        preview_result = await_preview(
            args.output / "live" / "frames" / f"{source_key}.detector-1.json",
            identified.date.isoformat(),
        )
    return counts, timeline, document, preview_result


def run(args) -> dict:
    from ultralytics import YOLO

    if args.output.exists():
        raise ValueError(
            "Use a fresh --output directory so previous sightings cannot affect this smoke"
        )
    args.output.mkdir(parents=True)
    capture = cv2.VideoCapture(str(args.video))
    ok, first_frame = capture.read()
    if not ok:
        raise ValueError("Cannot decode local video")
    crops, annotation_metadata = annotated_crops(
        args.annotations, args.source_pickle, first_frame
    )
    encoder = MiewidEncoder(
        args.output / "models", device=args.device, weights=args.weights
    )
    parity_result = parity(encoder, args.weights, list(crops.values()), args.device)
    counted = CountedEncoder(encoder)
    cache = EmbeddingCache(args.output / "embeddings.sqlite")
    catalog = IdentityCatalog(args.output / "identity")
    settings = IdentityConfig(labels=("cow",))
    identifier = GalleryIdentifier(settings, catalog, counted, cache)
    detector = YOLO(str(args.detector))
    started = time.perf_counter()
    try:
        counts, timeline, document, preview_result = collect_video(
            capture, args, catalog, crops, identifier, detector
        )
        if catalog.load() != document:
            raise AssertionError(
                "Predictions changed the independently seeded identity catalog"
            )
        gallery_images = [
            catalog.read_image(sample)
            for item in document.identities
            for sample in item.samples
        ]
        before = counted.calls
        first = cache.encode(counted, gallery_images)
        second = cache.encode(counted, gallery_images)
        np.testing.assert_array_equal(first, second)
        if counted.calls != before:
            raise AssertionError(
                "Existing gallery vectors unexpectedly required a model pass"
            )
        live_boxes = preview_result["boxes"]
        if not live_boxes or any(
            set(box["identity"]) != {"id", "name", "similarity"} for box in live_boxes
        ):
            raise AssertionError(
                "Live browser payload did not include the identity contract"
            )
        counts["retained_sightings"] = len(
            list((catalog.directory / "sightings").glob("*.json"))
        )
        counts["encoder_calls"] = counted.calls
        counts["encoded_images"] = counted.images
    finally:
        capture.release()
        cache.close()
    return {
        "purpose": "Same-clip production integration smoke; not independent identity accuracy",
        "video_seconds": args.seconds,
        "sample_fps": 1,
        "device": args.device,
        "elapsed_processing_seconds": time.perf_counter() - started,
        "inputs_sha256": {
            "video": digest(args.video),
            "annotations": digest(args.annotations),
            "detector_weights": digest(args.detector),
            "identity_weights": digest(args.weights),
        },
        "annotation_source": annotation_metadata,
        "production_encoder_parity": parity_result,
        "encoder_fingerprint": encoder.fingerprint,
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "torchvision",
                "timm",
                "ultralytics",
                "numpy",
                "pillow",
            )
        },
        "settings": settings.model_dump(mode="json"),
        "counts": counts,
        "timeline": timeline,
        "checks": {
            "empty_gallery_collection": True,
            "explicit_publisher_label_enrollment": True,
            "gallery_unchanged_by_predictions": True,
            "repeat_gallery_zero_inference": True,
            "box_coordinates_preserved": True,
            "live_identity_fields_published": True,
        },
        "limitations": [
            "Only 30 seconds of one public scene, sampled at 1 fps.",
            "Two first-frame publisher examples; subsequent same-clip predictions are not independent validation.",
            "No accuracy/identity-switch metric claimed; localization and tracking are not scored against labels.",
            "Live JSON publication is tested; browser rendering is tested separately.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument(
        "--source-pickle", type=Path, required=True, help="Hashed only, never executed"
    )
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, choices=range(4, 61), default=30)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    result = run(args)
    result["script_sha256"] = digest(Path(__file__))
    write_json(args.output / "summary.json", result)
    print(
        json.dumps(
            {"counts": result["counts"], "parity": result["production_encoder_parity"]}
        )
    )


if __name__ == "__main__":
    main()
