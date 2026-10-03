"""Frozen production-policy check on a temporally held-out public calf video.

Publisher annotations are read from numeric NPZ or the included JSON panel.
The original pickle is hashed for provenance and never deserialized. Images
stay local. The JSON panel preserves the previous numeric conversion exactly.
"""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import lap
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json
from smoke_runtime import CountedEncoder

from aidetector.adapters.identity_catalog import (
    Catalog,
    EnrolledIdentity,
    IdentityCatalog,
)
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    usable_crop,
)
from aidetector.adapters.inference.miewid import MiewidEncoder
from aidetector.adapters.inference.yolo import map_observations
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, Frame, IdentityMatch, Observation

ENROLLED = tuple(range(1, 7))
ENROLL_SECONDS = (0, 10, 20)
DETECTOR_PROTOCOLS = {
    "preset": dict(imgsz=960, conf=0.6, tracker="bytetrack.yaml", quantize=16),
    "alternate": dict(imgsz=640, conf=0.25, tracker="bytetrack.yaml", quantize=16),
    "oracle": {},
}


def detector_libraries():
    versions = {
        name: importlib.metadata.version(name)
        for name in ("torch", "torchvision", "ultralytics", "lap", "numpy")
    }
    versions["opencv"] = cv2.__version__
    try:
        versions["scipy"] = importlib.metadata.version("scipy")
    except importlib.metadata.PackageNotFoundError:
        versions["scipy"] = None
    return versions


class CachedEncoder:
    """Cache research queries without changing any GalleryIdentifier decisions."""

    def __init__(self, encoder, cache):
        self.encoder, self.cache = encoder, cache
        self.fingerprint, self.dimension = encoder.fingerprint, encoder.dimension

    def encode(self, images):
        return self.cache.encode(self.encoder, images)


def annotations(args):
    if args.annotations.suffix == ".json":
        panel = json.loads(args.annotations.read_text())
        metadata = panel["metadata"]
        records = {key: np.asarray(values) for key, values in panel["records"].items()}
    else:
        with np.load(args.annotations, allow_pickle=False) as arrays:
            metadata = json.loads(str(arrays["metadata_json"]))
            records = {
                key: arrays[key].copy()
                for key in (
                    "frame_id",
                    "cow_id",
                    "x_center",
                    "y_center",
                    "width",
                    "height",
                )
            }
    if metadata["source_sha256"] != digest(args.source_pickle):
        raise ValueError("Safe annotations do not match the publisher source")
    if metadata["coordinate_convention"] != "normalized-center-width-height":
        raise ValueError("Unexpected publisher coordinate convention")
    return records, metadata


def truth_at(records, frame_id, width, height):
    rows = []
    for index in np.flatnonzero(records["frame_id"] == frame_id):
        x, y, w, h = (
            float(records[key][index])
            for key in ("x_center", "y_center", "width", "height")
        )
        bounds = [
            max(0, int((x - w / 2) * width)),
            max(0, int((y - h / 2) * height)),
            min(width, int((x + w / 2) * width)),
            min(height, int((y + h / 2) * height)),
        ]
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ValueError("Publisher annotation has an empty box")
        rows.append({"cow": int(records["cow_id"][index]), "box": bounds})
    if len({row["cow"] for row in rows}) != len(rows):
        raise ValueError("Duplicate publisher cow in one frame")
    return rows


def pixels_hash(image):
    value = hashlib.sha256(str((image.shape, image.dtype)).encode())
    value.update(image.tobytes())
    return value.hexdigest()


def read_frame(capture, second, fps):
    frame = round(second * fps)
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, image = capture.read()
    if not ok:
        raise ValueError(f"Video cannot decode second {second}")
    return frame + 1, image


def seed_gallery(catalog, capture, records, fps):
    samples = {cow: [] for cow in ENROLLED}
    manifest = []
    for second in ENROLL_SECONDS:
        frame_id, image = read_frame(capture, second, fps)
        truth = truth_at(records, frame_id, image.shape[1], image.shape[0])
        for row in truth:
            cow = row["cow"]
            if cow not in samples:
                continue
            x1, y1, x2, y2 = row["box"]
            crop = image[y1:y2, x1:x2].copy()
            sample = catalog.save_sighting(
                crop,
                "publisher-enrollment",
                datetime(2000, 1, 1, tzinfo=UTC),
                None,
                IdentityMatch(),
            )
            if sample is None:
                raise ValueError("Could not retain publisher enrollment example")
            samples[cow].append(sample)
            manifest.append(
                {
                    **row,
                    "second": second,
                    "publisher_frame": frame_id,
                    "pixels_sha256": pixels_hash(crop),
                    "saved_jpeg_sha256": digest(
                        catalog.directory / "images" / f"{sample}.jpg"
                    ),
                }
            )
    if any(len(items) != 3 for items in samples.values()):
        raise ValueError(
            "Every enrolled calf needs the three frozen publisher examples"
        )
    document = Catalog(
        revision=1,
        identities=tuple(
            EnrolledIdentity(
                id=f"{cow:032x}", name=f"Dataset calf {cow}", samples=tuple(items)
            )
            for cow, items in samples.items()
        ),
    )
    (catalog.directory / "catalog.json").write_text(document.model_dump_json(indent=2))
    return document, manifest


def pair_boxes(boxes, truth, minimum=0.5):
    """Maximum-cardinality matching, then maximize IoU among valid pairs."""
    if not boxes or not truth:
        return {}
    overlaps = np.zeros((len(boxes), len(truth)), dtype=float)
    for i, box in enumerate(boxes):
        for j, row in enumerate(truth):
            x1, y1, x2, y2 = row["box"]
            intersection = max(0, min(box.x2, x2) - max(box.x1, x1)) * max(
                0, min(box.y2, y2) - max(box.y1, y1)
            )
            union = (
                (box.x2 - box.x1) * (box.y2 - box.y1)
                + (x2 - x1) * (y2 - y1)
                - intersection
            )
            overlaps[i, j] = intersection / union
    weights = np.where(
        overlaps >= minimum, min(len(boxes), len(truth)) + 1 + overlaps, 0
    )
    _, assignments, _ = lap.lapjv(-weights, extend_cost=True)
    return {
        int(i): int(j)
        for i, j in enumerate(assignments)
        if j >= 0 and overlaps[i, j] >= minimum
    }


class VideoMetrics:
    def __init__(self):
        self.counts = Counter(
            {
                key: 0
                for key in (
                    "correct_name",
                    "wrong_name",
                    "unknown_named",
                    "unmatched_named",
                    "cow_name_switches",
                )
            }
        )
        self.names = Counter()
        self.cow_tracks = {}
        self.track_cows = {}
        self.cow_names = {}

    def changed(self, memory, key, value, second):
        previous = memory.get(key)
        memory[key] = (second, value)
        return (
            previous is not None and second - previous[0] <= 5 and previous[1] != value
        )

    def add(self, second, boxes, truth, eligible):
        paired = pair_boxes(boxes, truth)
        c = self.counts
        c.update(
            frames=1,
            visible_annotations=len(truth),
            visible_known=sum(row["cow"] in ENROLLED for row in truth),
            visible_unknown=sum(row["cow"] not in ENROLLED for row in truth),
            detector_boxes=len(boxes),
            matched_boxes=len(paired),
            eligible_boxes=sum(eligible),
            eligible_matched=sum(eligible[i] for i in paired),
            missed_annotations=len(truth) - len(paired),
            unmatched_boxes=len(boxes) - len(paired),
        )
        decisions = []
        for index, box in enumerate(boxes):
            named = (
                int(box.identity.identity_id, 16)
                if box.identity and box.identity.identity_id
                else None
            )
            actual = truth[paired[index]]["cow"] if index in paired else None
            if actual is None:
                outcome = (
                    "unmatched_named" if named is not None else "unmatched_unnamed"
                )
            elif named is None:
                outcome = "known_unnamed" if actual in ENROLLED else "unknown_rejected"
            elif actual not in ENROLLED:
                outcome = "unknown_named"
            else:
                outcome = "correct_name" if named == actual else "wrong_name"
            c[outcome] += 1
            self.names[
                f"{actual if actual is not None else 'unmatched'}->{named if named is not None else 'unknown'}"
            ] += 1
            if actual is not None and box.track_id is not None:
                c["cow_track_switches"] += self.changed(
                    self.cow_tracks, actual, box.track_id, second
                )
                c["track_cow_switches"] += self.changed(
                    self.track_cows, box.track_id, actual, second
                )
            if actual is not None and named is not None:
                c["cow_name_switches"] += self.changed(
                    self.cow_names, actual, named, second
                )
            decisions.append(
                {
                    "box": [box.x1, box.y1, box.x2, box.y2],
                    "track": box.track_id,
                    "truth": actual,
                    "name": named,
                    "similarity": box.identity.similarity if box.identity else None,
                    "eligible": eligible[index],
                    "outcome": outcome,
                }
            )
        return decisions


class VideoDetector:
    """Cache only complete, provenance-matched detector sequences, including tracks."""

    def __init__(self, args, video_hash):
        from ultralytics import YOLO
        from ultralytics.utils import ROOT

        self.options = DETECTOR_PROTOCOLS[args.mode]
        self.model = None if args.mode == "oracle" else YOLO(str(args.detector))
        self.classes = (
            {}
            if self.model is None
            else {
                key: ("cow", self.options["conf"])
                for key, name in self.model.names.items()
                if name == "cow"
            }
        )
        if self.model is not None and len(self.classes) != 1:
            raise ValueError("Detector must expose exactly one cow class")
        self.provenance = {
            "version": 3,
            "video": video_hash,
            "weights": digest(Path(self.model.ckpt_path)) if self.model else None,
            "options": self.options,
            "mode": args.mode,
            "device": args.device,
            "start": args.start,
            "seconds": 300,
            "tracker_sha256": digest(ROOT / "cfg/trackers/bytetrack.yaml"),
            "libraries": detector_libraries(),
        }
        key = hashlib.sha256(
            json.dumps(self.provenance, sort_keys=True).encode()
        ).hexdigest()
        self.path = args.cache / f"detections-{key}.json"
        self.previous = (
            json.loads(self.path.read_text()) if self.path.exists() else None
        )
        self.records = []
        self.backend = self.previous["backend"] if self.previous else None

    def observe(self, image, at, second, truth):
        image_hash = pixels_hash(image)
        if self.previous is not None:
            cached = self.previous["frames"][len(self.records)]
            if cached["second"] != second or cached["pixels_sha256"] != image_hash:
                raise ValueError("Detector cache does not match this video frame")
            observation = Observation(
                at, image, {}, tuple(BoundingBox(**box) for box in cached["boxes"])
            )
        elif self.model is None:
            # Stable opaque tracking IDs identify continuity only. The matcher
            # never receives the publisher ID as a recognition label.
            boxes = tuple(
                BoundingBox(*row["box"], "cow", 1.0, row["cow"] + 1000) for row in truth
            )
            observation = Observation(at, image, {"cow": 1.0}, boxes)
            self.backend = {
                "device": "publisher annotations",
                "precision": "not applicable",
            }
        else:
            result = self.model.track(
                image,
                persist=True,
                device=self.provenance["device"],
                classes=list(self.classes),
                verbose=False,
                **self.options,
            )[0]
            observation = map_observations(result, (Frame(at, image),), self.classes)[0]
            backend = self.model.predictor.model
            self.backend = {
                "device": str(backend.device),
                "precision": "FP16" if backend.fp16 else "FP32",
            }
        self.records.append(
            {
                "second": second,
                "pixels_sha256": image_hash,
                "boxes": [asdict(box) for box in observation.boxes],
            }
        )
        return observation

    def save(self):
        write_json(self.path, {"backend": self.backend, "frames": self.records})


def evaluate(args, capture, fps, records, identifier, detector):
    metrics, timeline, durations = VideoMetrics(), [], Counter()
    started = time.perf_counter()
    for index, second in enumerate(range(args.start, args.start + 300)):
        tick = time.perf_counter()
        frame_id, image = read_frame(capture, second, fps)
        durations["decode_seconds"] += time.perf_counter() - tick
        truth = truth_at(records, frame_id, image.shape[1], image.shape[0])
        at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=second)
        tick = time.perf_counter()
        observation = detector.observe(image, at, second, truth)
        durations["detector_seconds"] += time.perf_counter() - tick
        settings = identifier.settings
        eligible = [
            usable_crop(
                box,
                observation.boxes,
                image.shape[1],
                image.shape[0],
                settings.min_crop_size,
                settings.max_overlap,
            )
            for box in observation.boxes
        ]
        tick = time.perf_counter()
        identified = identifier.identify("public-8-calves-heldout", observation)
        durations["identity_seconds"] += time.perf_counter() - tick
        decisions = metrics.add(second, identified.boxes, truth, eligible)
        timeline.append(
            {
                "second": second,
                "publisher_frame": frame_id,
                "pixels_sha256": pixels_hash(image),
                "annotations": len(truth),
                "decisions": decisions,
            }
        )
        if (index + 1) % 30 == 0:
            print(
                json.dumps(
                    {
                        "frames": index + 1,
                        "elapsed_seconds": round(time.perf_counter() - started, 1),
                        **{
                            key: metrics.counts[key]
                            for key in ("correct_name", "wrong_name", "unknown_named")
                        },
                    }
                ),
                flush=True,
            )
    return (
        metrics,
        timeline,
        {**dict(durations), "total_seconds": time.perf_counter() - started},
    )


def summarize(args, metrics, durations, raw, detector):
    c = metrics.counts
    named = c["correct_name"] + c["wrong_name"] + c["unknown_named"]
    return {
        "purpose": "Development-panel held-out-video assessment of unchanged production GalleryIdentifier; oracle mode is a diagnostic upper-bound input, not app accuracy",
        "manifest_sha256": digest(args.output / "manifest.json"),
        "counts": dict(c),
        "confusion_counts": dict(metrics.names),
        "rates": {
            "detection_coverage_all_visible": c["matched_boxes"]
            / c["visible_annotations"],
            "eligible_coverage_all_visible": c["eligible_matched"]
            / c["visible_annotations"],
            "correct_name_coverage_known_visible": c["correct_name"]
            / c["visible_known"],
            "unknown_false_name_rate_visible": c["unknown_named"]
            / c["visible_unknown"],
            "matched_name_precision": c["correct_name"] / named if named else None,
        },
        "timing": durations,
        "detector_cache_reused": detector.previous is not None,
        "actual_detector_backend": detector.backend,
        "actual_identity_backend": {
            "device": raw.encoder.device,
            "precision": str(next(raw.encoder.model.parameters()).dtype),
        },
        "new_encoder_batches": raw.calls,
        "new_encoded_images": raw.images,
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "torchvision",
                "timm",
                "ultralytics",
                "numpy",
                "pillow",
                "lap",
            )
        },
        "limitations": [
            "One public pen video, eight calves; correlated 1 fps observations, no confidence intervals.",
            "Enrollment uses three fixed early publisher crops, not farmer-curated diverse appearances.",
            "IDs 1–6 enrolled; IDs 7–8 withheld. Last enrollment at 20 s; queries start at least 310 s later.",
            "One-to-one localization matching uses IoU >= .5. Unmatched named boxes are reported separately, not counted as confirmed correct or wrong.",
            "Track/name switches count adjacent matched observations with at most 5 s gap; not a complete MOTChallenge metric.",
            "Thresholds frozen at defaults; no calibration or threshold tuning.",
            "Detector tracks sampled 1 fps inputs; this is not full-frame-rate tracking.",
            "Oracle boxes and stable publisher track IDs are an explicit diagnostic control, not deployable information.",
        ],
    }


def run(args):
    if args.output.exists():
        raise ValueError(
            "Choose a fresh output directory; reuse only --cache for repeated runs"
        )
    args.output.mkdir(parents=True)
    records, metadata = annotations(args)
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        raise ValueError("Video has no valid frame rate")
    catalog = IdentityCatalog(args.output / "gallery")
    document, enrollment = seed_gallery(catalog, capture, records, fps)
    settings = IdentityConfig(labels=("cow",))
    if (settings.min_similarity, settings.min_margin, settings.min_observations) != (
        0.65,
        0.1,
        3,
    ):
        raise ValueError("Frozen assessment requires the original .65/.10/3 policy")
    raw = CountedEncoder(
        MiewidEncoder(args.cache / "models", device=args.device, weights=args.weights)
    )
    gallery_cache = EmbeddingCache(args.cache / "gallery.sqlite")
    query_cache = EmbeddingCache(args.cache / "queries.sqlite")
    identifier = GalleryIdentifier(
        settings, catalog, CachedEncoder(raw, query_cache), gallery_cache
    )
    hashes = {
        "video": digest(args.video),
        "annotations": digest(args.annotations),
        "identity": digest(args.weights),
        "script": digest(Path(__file__)),
    }
    detector = VideoDetector(args, hashes["video"])
    manifest = {
        "version": 2,
        "source_hashes": hashes,
        "annotation_source": metadata,
        "enrolled_ids": ENROLLED,
        "unknown_ids": [7, 8],
        "enrollment": enrollment,
        "query_seconds": list(range(args.start, args.start + 300)),
        "fps": fps,
        "settings": settings.model_dump(mode="json"),
        "detector": detector.provenance,
        "encoder_fingerprint": raw.fingerprint,
    }
    write_json(args.output / "manifest.json", manifest)
    try:
        metrics, timeline, durations = evaluate(
            args, capture, fps, records, identifier, detector
        )
        if catalog.load() != document:
            raise AssertionError("Predictions changed confirmed enrollment")
    finally:
        capture.release()
        gallery_cache.close()
        query_cache.close()
    detector.save()
    result = summarize(args, metrics, durations, raw, detector)
    write_json(args.output / "summary.json", result)
    write_json(args.output / "timeline.json", timeline)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in (
        "video",
        "annotations",
        "source-pickle",
        "detector",
        "weights",
        "output",
        "cache",
    ):
        parser.add_argument(f"--{field}", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--mode", choices=tuple(DETECTOR_PROTOCOLS), default="preset")
    parser.add_argument("--start", type=int, choices=(330, 930), default=330)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
