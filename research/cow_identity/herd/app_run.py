"""Name the cows of one video with the application's own detector and identifier.

Nothing here decides anything: frames are shrunk as a camera source shrinks
them, the detector adapter tracks, and the identifier learns the confirmed herd
and applies the shipped preset. The run records every box, the name the
application showed on it, and the similarities behind that decision, so the
rules can be replayed and the names scored without running a model again.
"""

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import Executor, Future
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from enroll import write_herd
from ethz import VIDEOS, confirmed_before
from video_identify import fewer_confirmations

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.inference.herd_gallery import prepare_herd
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    distinct_identity_scores,
    infrared,
)
from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.inference.yolo import open_detector
from aidetector.adapters.media.images import shrink_image
from aidetector.configuration import Config
from aidetector.domain.models import Frame
from aidetector.version import TYPE

SOURCE = "evaluated-video"


class Immediately(Executor):
    """Learn the herd before the first frame instead of beside it."""

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future


def detector_config(preset, detector_weights, source=SOURCE + ".mp4"):
    """The shipped preset, with its detector model taken from local disk."""
    settings = json.loads(Path(preset).read_text())
    settings.setdefault("detection", {})["source"] = str(source)
    settings["yolo"]["model"] = str(Path(detector_weights).resolve())
    return settings


def preset_config(preset, detector_weights, herd_weights, source=SOURCE + ".mp4"):
    """The shipped preset, with its two model files taken from local disk."""
    settings = detector_config(preset, detector_weights, source)
    settings["identity"]["weights"] = str(Path(herd_weights).resolve())
    return Config.model_validate({"detectors": [settings]})


def taught_cows(gallery, cow_of):
    """The publisher numbers of the taught cows, in the order of their scores."""
    return [cow_of[identity] for identity, _ in dict.fromkeys(gallery.owners)]


def identity_scores(gallery, crops):
    """The application's own score of every crop for every taught cow."""
    matches = distinct_identity_scores(
        gallery.encoder.encode(crops),
        gallery.vectors,
        gallery.owners,
        gallery.neighbours,
        gallery.parts,
    )
    return np.array([[match.similarity for match in row] for row in matches])


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Publisher crops to confirm")
    parser.add_argument("--video", required=True, choices=sorted(VIDEOS))
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument("--either-side", action="store_true", help="Development only")
    parser.add_argument("--confirmations", type=int)
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--detector-weights", type=Path, required=True)
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--data", type=Path, required=True, help="Empty data folder")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()),
        arguments.video,
        set(arguments.enrolled),
        either_side=arguments.either_side,
    )
    if arguments.confirmations:
        rows = fewer_confirmations(rows, arguments.confirmations)
    identities = write_herd(rows, arguments.manifest.parent, arguments.data)
    cow_of = {identity: cow for cow, identity in identities.items()}
    config = preset_config(
        arguments.preset, arguments.detector_weights, arguments.herd_weights
    )
    settings = config.detectors[0]
    width = settings.detection.frames_width
    store = IdentityCatalog(arguments.data / "identities")
    prepare = partial(
        prepare_herd,
        store=store,
        cattle_start=Path(settings.identity.weights),
        animal_start=arguments.animal_weights,
        directory=arguments.data / "identities" / "herd",
    )
    started = time.perf_counter()
    gallery = prepare(store.load())
    learning_seconds = time.perf_counter() - started
    # The identifier asks for the same catalog and reloads the saved model.
    identifier = GalleryIdentifier(settings.identity, store, prepare, Immediately())
    classes = taught_cows(gallery, cow_of)

    index = json.loads((arguments.frames / "frames.json").read_text())
    start = datetime.fromisoformat(VIDEOS[arguments.video]["start"])
    boxes, shown, scores, detect_seconds, identify_seconds = [], [], [], [], []
    models = (ModelRequirements(settings.yolo.model, settings.yolo.imgsz, 1),)
    with (
        inference_runtime(config.onnx, models, TYPE) as options,
        open_detector(settings.yolo, config.onnx, (SOURCE,), TYPE, options) as detector,
    ):
        for step, sampled in enumerate(index["frames"]):
            original = cv2.imread(str(arguments.frames / sampled["file"]))
            image = shrink_image(original, width)
            scale = original.shape[1] / image.shape[1]
            # The source hands the detector one frame per second.
            frame = Frame(start + timedelta(seconds=step), image)
            started = time.perf_counter()
            observation = detector.detect({SOURCE: (frame,)})[SOURCE][-1]
            detected = time.perf_counter()
            named = identifier.identify(SOURCE, observation)
            identified = time.perf_counter()
            detect_seconds.append(detected - started)
            identify_seconds.append(identified - detected)
            crops = []
            for box in named.boxes:
                boxes.append(
                    {
                        "index": sampled["index"],
                        "seconds": float(step),
                        "app_box": [box.x1, box.y1, box.x2, box.y2],
                        "app_size": [image.shape[1], image.shape[0]],
                        "box": [value * scale for value in (box.x1, box.y1, box.x2, box.y2)],
                        "frame_size": [original.shape[1], original.shape[0]],
                        "infrared": infrared(image),
                        "track": box.track_id,
                        "confidence": box.confidence,
                    }
                )
                shown.append(
                    cow_of[box.identity.identity_id]
                    if box.identity is not None and box.identity.identity_id
                    else None
                )
                crops.append(image[box.y1 : box.y2, box.x1 : box.x2])
            if crops:
                scores.append(identity_scores(gallery, crops))

    warm_detect = np.array(detect_seconds[10:])
    warm_identify = np.array(identify_seconds[10:])
    warm_total = warm_detect + warm_identify

    def spread(values):
        return {
            "mean": float(values.mean()),
            "p95": float(np.quantile(values, 0.95)),
            "max": float(values.max()),
        }

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        arguments.output.with_suffix(".npz"),
        scores=np.concatenate(scores) if scores else np.empty((0, len(classes))),
        classes=np.array(classes),
    )
    arguments.output.write_text(
        json.dumps(
            {
                "video": arguments.video,
                "enrolled": sorted(arguments.enrolled),
                "either_side": arguments.either_side,
                "confirmed_photographs": len(rows),
                "confirmations": len({(row["cow"], row["clip"]) for row in rows}),
                "photographs_per_cow": {
                    str(cow): sum(row["cow"] == cow for row in rows) for cow in classes
                },
                "latest_photograph": max(row["date"] + row["time"] for row in rows),
                "preset": json.loads(arguments.preset.read_text()),
                "detector_weights_sha256": digest(arguments.detector_weights),
                "herd_weights_sha256": digest(arguments.herd_weights),
                "animal_weights_sha256": digest(arguments.animal_weights),
                "device": gallery.encoder.device,
                "learning_seconds": learning_seconds,
                "frames": len(index["frames"]),
                "seconds_per_frame": {
                    "detect_and_track": spread(warm_detect),
                    "identify": spread(warm_identify),
                    "total": spread(warm_total),
                },
                "boxes": boxes,
                "shown": shown,
            }
        )
        + "\n"
    )
    print(
        f"{arguments.video}: {len(boxes)} boxes, {sum(name is not None for name in shown)} named; "
        f"learning {learning_seconds:.0f}s; {warm_total.mean() * 1000:.0f} ms/frame "
        f"(p95 {np.quantile(warm_total, 0.95) * 1000:.0f}, max {warm_total.max() * 1000:.0f})"
    )


if __name__ == "__main__":
    main()
