"""Actual application/capture/collection proof; only camera hardware is simulated."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import resource
import shutil
import sqlite3
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

from aidetector.adapters.identity_profile_collector import IdentityProfileCollector
from aidetector.adapters.inference import cutie_runtime, yolo
from aidetector.adapters.inference.continuous_models import CUTIE_URL, SAM_URL
from aidetector.adapters.live_preview import LivePreview
from aidetector.adapters.operational_status import source_key
from aidetector.bootstrap import run_application
from aidetector.configuration import Config

ROOT = Path(__file__).parent
CLIP = Path(".cache/cow-cutie/calibration-clip")
YOLO = Path(".cache/cow-detectors/training/mixed-full-backbone/weights/best.pt")
CUTIE = Path(".cache/cow-cutie/cutie-base-mega.pth")
SAM = Path(".cache/cow-segmentation/sam2.1_t.pt")
DURATION = 60.0


def sources():
    pending, found = ["aidetector.bootstrap"], set()
    while pending:
        module = pending.pop()
        base = Path("detector/src").joinpath(*module.split("."))
        path = base.with_suffix(".py")
        if not path.exists():
            path = base / "__init__.py"
        if not path.exists() or path in found:
            continue
        found.add(path)
        parts = module.split(".")
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("aidetector")
            ):
                pending.append(node.module)
            elif isinstance(node, ast.Import):
                pending.extend(
                    n.name for n in node.names if n.name.startswith("aidetector")
                )
    return found


def configuration():
    return Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {
                        "source": "0",
                        "interval": 9,
                        "frame_retention": 1,
                        "frames_width": 1280,
                    },
                    "yolo": {
                        "model": str(YOLO.resolve()),
                        "confidence": {"item": 0.4},
                        "imgsz": 640,
                        "iou": 0.7,
                        "tracking": False,
                        "frames_min": 1,
                    },
                    "identity": {"mode": "continuous", "labels": ["item"]},
                },
                {
                    "detection": {
                        "source": "1",
                        "interval": 0.5,
                        "frame_retention": 1,
                        "frames_width": 128,
                    }
                },
            ]
        }
    )


def freeze(path):
    files = sources() | {
        Path(__file__),
        ROOT / "test_application_bootstrap_proof.py",
        ROOT / "benchmark.py",
        ROOT / "video_assessment.py",
        CLIP / "sampled.json",
        CLIP / "sampled.avi",
        YOLO,
        CUTIE,
        SAM,
        Path("config/config.schema.json"),
    }
    files.update(Path("detector/vendor/cutie").glob("*.whl"))
    files.update(
        Path("detector/tests") / p
        for p in (
            "test_continuous_application.py",
            "adapters/test_identity_profile_collector.py",
            "adapters/test_identity_profiles.py",
        )
    )
    write_json(
        path,
        {
            "status": "FROZEN_BEFORE_APPLICATION_RUN",
            "files": {str(p): digest(p) for p in sorted(files)},
            "libraries": {
                n: importlib.metadata.version(n)
                for n in (
                    "torch",
                    "ultralytics",
                    "numpy",
                    "opencv-python",
                    "cutie",
                    "hydra-core",
                    "omegaconf",
                    "pydantic",
                )
            },
            "configuration": configuration().model_dump(mode="json", by_alias=True),
            "procedure": "Real run_application, real shared StreamPool/StreamSource and effective .5s retention4, YOLO/SAM/Cutie MPS/CPU, real profile SQLite. Only cv2.VideoCapture hardware replaced: source0 reads hash-bound exposed 0–60s pixels at synthetic10Hz by holding the2Hz samples; disconnect30s, reopen32s. Source1 is synthetic128x128 constant pixels at10Hz, ordinary snapshot rule. Real monotonic capture clock,60s after models open; subprocess total hardcap180s. No network/realcamera performance claim.",
            "instrumentation": "Forwarding observers at public LivePreview.observer and collector.__call__, plus public model context managers recording backend/cleanup. No policy/state/matching/private-method replacement. Pinned local model assets copied to empty data folder cache; normal bootstrap verifies pins.",
            "acceptance": "Automatic saved anonymous observations for both source0 epochs; no names/manual catalog or embedding DB; disjoint full instance generations across reconnect; source1 one epoch and processed before/after reconnect; onlysource0 profile facts; all published/evidence capture ages<1s; cleanup closes model contexts/captures/worker threads and SQLite write lock available.",
            "limits": {"driver_bytes": 8 * 1024**3, "rss_bytes": 8 * 1024**3},
            "limitations": "Mechanics proof, not biological identity accuracy, unseenfarm, entrance/reentry, network/RTSP stability, installation or long-term mask accuracy. Synthetic second camera cannot validate multi-camera inference performance. Existing late-panel failures remain.",
        },
    )


def checked(path):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    if value["libraries"] != {
        name: importlib.metadata.version(name) for name in value["libraries"]
    }:
        raise ValueError("Library versions changed")
    return value


@dataclass
class Audit:
    limits: dict
    statuses: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    backends: dict = field(default_factory=dict)
    closed: list = field(default_factory=list)
    peak_driver: int = 0
    peak_rss: int = 0

    def resource(self):
        import torch

        self.peak_driver = max(self.peak_driver, torch.mps.driver_allocated_memory())
        self.peak_rss = max(
            self.peak_rss, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        )
        if (
            self.peak_driver > self.limits["driver_bytes"]
            or self.peak_rss > self.limits["rss_bytes"]
        ):
            raise MemoryError("Frozen application resource bound exceeded")

    def status(self, event):
        self.statuses.append({"at": time.monotonic(), **asdict(event)})
        if event.kind in {"inference", "processed"}:
            self.resource()
        if event.kind in {
            "source_epoch",
            "offline",
            "identity_collecting",
            "identity_ready",
            "notice",
        }:
            print(json.dumps(asdict(event)), flush=True)

    def observe(self, source, value):
        age = time.monotonic() - value.capture.monotonic_at
        if not 0 <= age < 1:
            raise AssertionError("Published stale observation")
        if any(
            box.identity is not None and box.identity.identity_id is not None
            for box in value.boxes
        ):
            raise AssertionError("Anonymous application invented an identity")
        self.observations.append(
            {
                "source": source,
                "epoch": value.capture.epoch,
                "sequence": value.capture.sequence,
                "age": age,
                "boxes": len(value.boxes),
            }
        )

    def collect(self, evidence):
        age = time.monotonic() - evidence.capture.monotonic_at
        if not 0 <= age < 1 or evidence.image.flags.writeable:
            raise AssertionError("Invalid anonymous evidence boundary")
        self.evidence.append(
            {
                "source": evidence.source,
                "epoch": evidence.capture.epoch,
                "sequence": evidence.capture.sequence,
                "generation": evidence.target.generation,
                "instance": evidence.target.instance_id,
                "analysis_index": evidence.analysis_index,
                "age": age,
            }
        )


class Cameras:
    """Hardware fixture only; real production capture thread creates epochs/stamps."""

    def __init__(self, original, rows, stop):
        self.original, self.rows, self.stop = original, rows, stop
        self.origin = None
        self.lock = threading.Lock()
        self.opened, self.released, self.inputs = [], [], []
        self.timer = None

    def begin(self):
        with self.lock:
            if self.origin is None:
                self.origin = time.monotonic()
                self.timer = threading.Timer(DURATION, self.stop.set)
                self.timer.start()
            return self.origin

    def __call__(self, source, *args):
        if source not in (0, 1):
            raise AssertionError(f"Unexpected camera access: {source}")
        self.opened.append(source)
        return Capture(self, source)


class Capture:
    def __init__(self, cameras, source):
        self.cameras, self.source = cameras, source
        self.reader = (
            cameras.original(str(CLIP / "sampled.avi")) if source == 0 else None
        )
        self.index, self.image, self.due = -1, None, None
        self.closed = False

    def isOpened(self):
        return self.reader.isOpened() if self.reader is not None else True

    def read(self):
        origin = self.cameras.begin()
        now = time.monotonic() - origin
        self.due = max(now, self.due if self.due is not None else now)
        if self.source == 0 and 30 <= now < 32:
            if self.index >= 0:
                return False, None
            self.due = 32
        if self.cameras.stop.wait(max(0, origin + self.due - time.monotonic())):
            return False, None
        second = time.monotonic() - origin
        self.due = second + 0.1
        if self.source == 0 and 30 <= second < 32:
            return False, None
        if self.source == 1:
            return True, np.full((128, 128, 3), 70, np.uint8)
        wanted = min(int(second * 2), 120)
        while self.index < wanted:
            ok, self.image = self.reader.read()
            if not ok:
                raise ValueError("Local fixture ended unexpectedly")
            self.index += 1
            if (
                pixels_hash(self.image)
                != self.cameras.rows[self.index]["pixels_sha256"]
            ):
                raise ValueError("Source pixels differ")
        self.cameras.inputs.append({"at": second, "sample": self.index})
        return True, self.image.copy()

    def release(self):
        if not self.closed:
            self.closed = True
            if self.reader is not None:
                self.reader.release()
            self.cameras.released.append(self.source)


def install_observers(stack, audit):
    observer, collect = LivePreview.observer, IdentityProfileCollector.__call__
    open_raw, open_tracker = yolo.open_detector, cutie_runtime.open_cutie

    def record_observer(preview, rule_id, sources):
        publish = observer(preview, rule_id, sources)

        def record(source, value):
            audit.observe(source, value)
            publish(source, value)

        return record

    def record_collection(collector, value):
        audit.collect(value)
        return collect(collector, value)

    @contextmanager
    def raw(*args, **kwargs):
        with open_raw(*args, **kwargs) as detector:
            try:
                yield detector
            finally:
                backend = detector.model.predictor.model
                audit.backends["yolo"] = {
                    "device": str(backend.device),
                    "fp16": backend.fp16,
                }
        audit.closed.append("yolo")

    @contextmanager
    def tracker(*args, **kwargs):
        with open_tracker(*args, **kwargs) as runtime:
            audit.backends["cutie"] = {"device": runtime.device, "dtype": "float32"}
            yield runtime
        audit.closed.append("cutie")

    stack.enter_context(patch.object(LivePreview, "observer", record_observer))
    stack.enter_context(
        patch.object(IdentityProfileCollector, "__call__", record_collection)
    )
    stack.enter_context(patch.object(yolo, "open_detector", raw))
    stack.enter_context(patch.object(cutie_runtime, "open_cutie", tracker))


def prepare_data(path):
    if path.exists():
        raise ValueError("Application data folder must be new")
    path.mkdir(parents=True)
    for url, source in ((CUTIE_URL, CUTIE), (SAM_URL, SAM)):
        target = (
            path
            / "models"
            / "continuous"
            / hashlib.sha256(url.encode()).hexdigest()[:16]
            / source.name
        )
        target.parent.mkdir(parents=True)
        shutil.copyfile(source, target)
        if digest(source) != digest(target):
            raise ValueError("Cached asset copy differs")


def saved_facts(directory):
    with sqlite3.connect(directory / "identities/automatic/profiles.sqlite") as db:
        db.execute("BEGIN EXCLUSIVE")
        facts = [
            json.loads(row[0])
            for row in db.execute("SELECT facts FROM candidates ORDER BY saved_at,id")
        ]
        images = {
            key: bytes(jpeg) for key, jpeg in db.execute("SELECT id,jpeg FROM images")
        }
        for item in facts:
            data = images[item["encoded_sha256"]]
            if hashlib.sha256(data).hexdigest() != item[
                "encoded_sha256"
            ] or cv2.imdecode(
                np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
            ).shape != tuple(item["image_shape"]):
                raise AssertionError("Stored full-resolution JPEG differs")
        db.rollback()
    return facts


def assertions(audit, cameras, directory, facts):
    epochs = {
        source: {
            e["source_epoch"]
            for e in audit.statuses
            if e["kind"] == "source_epoch" and e["source"] == source
        }
        for source in ("0", "1")
    }
    assert len(epochs["0"]) == 2 and len(epochs["1"]) == 1, epochs
    assert {f["epoch"] for f in facts} == epochs["0"] and facts
    assert {f["source_key"] for f in facts} == {source_key("0")}
    assert all(
        f["status"] == "anonymous_observation_not_biological_identity" for f in facts
    )
    groups = [
        {(f["instance_id"], f["generation"]) for f in facts if f["epoch"] == epoch}
        for epoch in sorted(epochs["0"])
    ]
    assert not groups[0] & groups[1]
    assert not (directory / "identities/catalog.json").exists()
    assert not (directory / "identities/embeddings.sqlite").exists()
    assert sorted(cameras.opened) == sorted(cameras.released)
    assert set(audit.closed) == {"yolo", "cutie"}
    assert all(v["device"].startswith("mps") for v in audit.backends.values())
    second = [
        e["at"] - cameras.origin
        for e in audit.statuses
        if e["kind"] == "processed" and e["source"] == "1"
    ]
    assert min(second) < 25 and max(second) > 35
    assert not any(
        t.name.startswith(("capture-", "detector-", "live-preview"))
        for t in threading.enumerate()
    )
    return {
        "source_epochs": {s: sorted(v) for s, v in epochs.items()},
        "saved_candidates": len(facts),
        "profiles": len({f["profile_id"] for f in facts}),
        "identity_catalog_created": False,
        "source_isolation": True,
        "cleanup": True,
        "sqlite_exclusive_lock_after_close": True,
    }


def run(protocol, output):
    value = checked(protocol)
    output.mkdir(parents=True, exist_ok=False)
    directory = output / "data"
    prepare_data(directory)
    audit = Audit(value["limits"])
    stop = threading.Event()
    cameras = Cameras(
        cv2.VideoCapture, json.loads((CLIP / "sampled.json").read_text())["rows"], stop
    )
    report = {"protocol_sha256": digest(protocol), "status": "INCOMPLETE"}
    start = time.monotonic()
    try:
        with ExitStack() as stack:
            install_observers(stack, audit)
            stack.enter_context(patch.object(cv2, "VideoCapture", cameras))
            stats = run_application(
                configuration(),
                Path.cwd(),
                directory,
                stop,
                audit.status,
                live_preview=True,
            )
        facts = saved_facts(directory)
        report.update(assertions(audit, cameras, directory, facts))
        report.update(
            status="PASS", statistics=[asdict(s) for s in stats], saved_facts=facts
        )
    except BaseException as error:
        report.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        stop.set()
        if cameras.timer is not None:
            cameras.timer.cancel()
            cameras.timer.join()
        report.update(
            elapsed_seconds=time.monotonic() - start,
            capture_seconds=time.monotonic() - cameras.origin
            if cameras.origin
            else None,
            audit=asdict(audit),
            captures={
                "opened": cameras.opened,
                "released": cameras.released,
                "source_inputs": cameras.inputs,
            },
        )
        write_json(output / "report.json", report)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in report.items()
                    if k not in {"audit", "captures", "saved_facts"}
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "check", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve existing freeze")
        freeze(args.protocol)
    elif args.mode == "check":
        print(json.dumps({"checked_files": len(checked(args.protocol)["files"])}))
    else:
        run(args.protocol, args.output)
