"""Play the mounting example to the whole application as a live camera.

The application gets Cow Catcher's mounting model and a Cow Identity detector
on one camera; its mounting recordings should then carry the names of the
cows in them. No mounting video with known cows exists, so the clip's cows
are confirmed from the clip itself and compared through the published
encoder, which needs no learning. That shows the path from camera to
recording and is no test of recognition.

The cow whose box lies most inside the mounting box is called Mounting cow;
the others are numbered by how far they lie inside it.
"""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from threading import Event, Thread, Timer

import cv2
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from app_run import detector_config

from aidetector.adapters.identity_catalog import Catalog, EnrolledIdentity
from aidetector.adapters.media.images import encode_jpeg, shrink_image
from aidetector.bootstrap import run_application
from aidetector.configuration import Config

# The stock detector's class number for a cow.
COW = 19
PORT = 8791


def identifier(text):
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def share_inside(box, outer):
    width = min(box[2], outer[2]) - max(box[0], outer[0])
    height = min(box[3], outer[3]) - max(box[1], outer[1])
    return max(0, width) * max(0, height) / ((box[2] - box[0]) * (box[3] - box[1]))


def confirm(clip, data, mounting_weights, detector_weights, width):
    """Write the clip's cows into the data folder as a confirmed herd; photographs by name."""
    mounting, animals = YOLO(str(mounting_weights)), YOLO(str(detector_weights))
    capture = cv2.VideoCapture(str(clip))
    crops, inside = defaultdict(list), defaultdict(list)
    index = 0
    while True:
        available, frame = capture.read()
        if not available:
            break
        if index % 5 == 0:
            image = shrink_image(frame, width)
            mounts = mounting.predict(image, conf=0.5, verbose=False)[0].boxes
            tracked = animals.track(
                image,
                imgsz=1280,
                conf=0.1,
                classes=[COW],
                tracker="bytetrack.yaml",
                persist=True,
                verbose=False,
            )[0].boxes
            mount = mounts.xyxy[int(mounts.conf.argmax())].tolist() if len(mounts) else None
            tracks = [] if tracked.id is None else tracked.id.int().tolist()
            for track, box in zip(tracks, tracked.xyxy.round().int().tolist(), strict=True):
                x1, y1, x2, y2 = box
                if min(x2 - x1, y2 - y1) >= 48:
                    crops[track].append(image[y1:y2, x1:x2].copy())
                    if mount:
                        inside[track].append(share_inside(box, mount))
        index += 1
    seen_enough = [track for track in crops if len(crops[track]) >= 12]
    ranked = sorted(seen_enough, key=lambda track: -median(inside[track] or [0]))[:8]
    names = ["Mounting cow", *(f"Cow {number}" for number in range(2, len(ranked) + 1))]
    images = data / "identities" / "images"
    images.mkdir(parents=True)
    herd = []
    for name, track in zip(names, ranked, strict=True):
        samples = []
        for number, crop in enumerate(crops[track]):
            samples.append(identifier(f"{name} {number}"))
            (images / f"{samples[-1]}.jpg").write_bytes(encode_jpeg(crop, quality=95))
        herd.append(EnrolledIdentity(id=identifier(name), name=name, samples=tuple(samples)))
    catalog = Catalog(revision=1, identities=tuple(herd))
    (images.parent / "catalog.json").write_text(catalog.model_dump_json())
    return {cow.name: len(cow.samples) for cow in herd}


def camera(clip):
    """The clip over HTTP as a camera sends it: picture by picture, at its own speed, in a loop."""
    capture = cv2.VideoCapture(str(clip))
    rate = capture.get(cv2.CAP_PROP_FPS)
    pictures = []
    while True:
        available, frame = capture.read()
        if not available:
            break
        pictures.append(encode_jpeg(frame, quality=90))

    class Camera(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=picture")
            self.end_headers()
            started, number = time.monotonic(), 0
            try:
                while True:
                    picture = pictures[number % len(pictures)]
                    self.wfile.write(
                        b"--picture\r\nContent-Type: image/jpeg\r\n"
                        b"Content-Length: %d\r\n\r\n%b\r\n" % (len(picture), picture)
                    )
                    number += 1
                    time.sleep(max(0.0, started + number / rate - time.monotonic()))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *arguments):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Camera)
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{PORT}/barn"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path, help="example/sprong24.mp4")
    parser.add_argument("--mounting-weights", type=Path, required=True)
    parser.add_argument("--detector-weights", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True, help="config/detector")
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--data", type=Path, required=True, help="Empty data folder")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    source = camera(arguments.clip)
    mounts = detector_config(
        arguments.presets / "cow-catcher.json", arguments.mounting_weights, source
    )
    del mounts["vlm"]
    identity = detector_config(
        arguments.presets / "cow-identity.json", arguments.detector_weights, source
    )
    # The published encoder compares at once; a herd of one clip is too small to learn from.
    identity["identity"] = {"labels": ["cow"], "min_crop_size": 32, "max_overlap": 1}
    config = Config.model_validate({"detectors": [mounts, identity]})
    confirmed = confirm(
        arguments.clip,
        arguments.data,
        arguments.mounting_weights,
        arguments.detector_weights,
        config.detectors[0].detection.frames_width,
    )

    ready = []

    def status(event):
        if event.kind == "identity_ready" and not ready:
            ready.append(datetime.now())

    stop = Event()
    Timer(arguments.seconds, stop.set).start()
    run_application(config, arguments.data, arguments.data, stop, status)

    recordings = [
        json.loads(path.read_text())
        for path in sorted((arguments.data / "detections" / "mounts").glob("*/*/metadata.json"))
    ]
    named = [
        {
            "start": recording["start"],
            "seconds": round(recording["duration"], 1),
            "names": [identity["name"] for identity in recording["identities"]],
        }
        for recording in recordings
        if datetime.fromisoformat(recording["start"]) >= ready[0]
    ]
    result = {
        "confirmed_photographs": confirmed,
        "recordings_before_the_herd_was_ready": len(recordings) - len(named),
        "recordings": named,
    }
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
