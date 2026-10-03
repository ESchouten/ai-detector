"""Frozen actual-model wrapper parity, then a paced reconnect mechanics check."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import resource
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import cv2
import numpy as np
from benchmark import digest, write_json
from video_assessment import pixels_hash

from aidetector.adapters.identity_catalog import IdentityCatalog
from aidetector.adapters.identity_control import LiveIdentityControl
from aidetector.adapters.inference.continuous_identity import ContinuousIdentityDetector
from aidetector.adapters.inference.cutie_runtime import open_cutie
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.adapters.inference.yolo import open_detector
from aidetector.adapters.sources.streams import CapturedFrame, StreamSource
from aidetector.configuration import OnnxConfig, YoloConfig
from aidetector.domain.live_identity import LiveIdentityState
from aidetector.domain.models import CaptureStamp, Frame

ROOT = Path(__file__).parent
BASE = Path(".cache/cow-startup-extended")
CLIP = Path(".cache/cow-cutie/calibration-clip")
YOLO = Path(".cache/cow-detectors/training/mixed-full-backbone/weights/best.pt")
CUTIE = Path(".cache/cow-cutie/cutie-base-mega.pth")
SAM = Path(".cache/cow-segmentation/sam2.1_t.pt")
SOURCE = "proof-camera"


def application_sources():
    """Bind the exercised import closure, not unrelated concurrently built features."""
    pending = [
        "aidetector.adapters.inference.continuous_identity",
        "aidetector.adapters.inference.yolo",
        "aidetector.adapters.sources.streams",
    ]
    found = set()
    while pending:
        module = pending.pop()
        base = Path("detector/src").joinpath(*module.split("."))
        path = (
            base.with_suffix(".py")
            if base.with_suffix(".py").exists()
            else base / "__init__.py"
        )
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
                    name.name
                    for name in node.names
                    if name.name.startswith("aidetector")
                )
    return sorted(found)


def freeze(path):
    baseline = json.loads((BASE / "streaming.json").read_text())
    if not baseline["complete"]:
        raise ValueError("Complete original automatic startup required")
    files = [
        Path(__file__),
        BASE / "streaming.json",
        CLIP / "sampled.json",
        CLIP / "sampled.avi",
        YOLO,
        CUTIE,
        SAM,
        ROOT / "benchmark.py",
        ROOT / "video_assessment.py",
    ]
    files.extend(application_sources())
    files.extend(Path("detector/vendor/cutie").glob("*.whl"))
    files.extend(BASE / "masks" / f"{i}.png" for i in range(121))
    files.extend(
        Path("detector/tests") / name
        for name in (
            "adapters/inference/test_continuous_identity.py",
            "adapters/test_identity_control.py",
        )
    )
    write_json(
        path,
        {
            "status": "FROZEN_BEFORE_ACTUAL_WRAPPER_INFERENCE",
            "files": {str(p): digest(p) for p in sorted(set(files))},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in (
                    "torch",
                    "ultralytics",
                    "numpy",
                    "opencv-python",
                    "cutie",
                    "hydra-core",
                    "omegaconf",
                )
            },
            "parity": "Actual existing YoloDetector, CPU SAM initializer and CutieRuntime inside ContinuousIdentityDetector. All241source inputs0–120 at2Hz,121integer raw proposals/masks/quality exact; all published geometry/eligible IDs/p10 exact. Frame0 startup and everyhalfstep intentionally omitted, no names assigned. Historical halfsecond masks unavailable. Offline injected capture clock isolates algorithm parity, not wallclock freshness.",
            "paced": "60s realwallclock preselected2Hz frames through StreamSource(retention4,interval0); initial source and one explicit disconnect at30s, noframes30–31.5, reconnect32s. Source timestamps actualmonotonic; wrapper clock is real. No synthetic frame-age override. Stop at60s. No accuracy scores. Reused exposed0–60pixels, no3000+.",
            "limits": {"driver_bytes": 8 * 1024**3, "rss_bytes": 8 * 1024**3},
            "cadence": {
                "interval": 0.5,
                "retention": 4,
                "catchup_max": 8,
                "reset_gap": 1,
            },
            "limitations": "Same known scene/checkpoints; no real RTSP transport, unseenfarm, biologicalID, entry/reentry, or installer claim. Prefix parity does not remove late accuracy failure.",
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


def box_record(box):
    return {name: getattr(box, name) for name in ("x1", "y1", "x2", "y2", "confidence")}


def eligible(row):
    probabilities = {
        item["track_id"] + 1: item["p10_probability"] for item in row["objects"]
    }
    return sorted(
        pair["track_id"] + 1
        for pair in row["reciprocal_pairs"]
        if pair["track_id"] + 1 not in row["conflicted_ids"]
        and (probabilities[pair["track_id"] + 1] or 0) >= 0.7
    )


@dataclass
class Audit:
    parity: bool
    baseline: dict
    current: dict | None = None
    now: float = 10
    raw_calls: int = 0
    steps: int = 0
    seeds: int = 0
    masks_equal: int = 0
    emitted: list = field(default_factory=list)
    events: list = field(default_factory=list)
    epochs: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    durations: list = field(default_factory=list)
    peak_driver: int = 0
    peak_rss: int = 0

    def clock(self):
        return self.now

    def evidence(self, value):
        if value.image.flags.writeable or value.box.identity.identity_id is not None:
            raise AssertionError("Evidence must be immutable and anonymous")
        now = self.now if self.parity else time.monotonic()
        age = now - value.capture.monotonic_at
        if not 0 <= age < 1:
            raise AssertionError("Published stale evidence")
        self.emitted.append((value.box.track_id, value.mask_p10))
        self.epochs.setdefault(value.capture.epoch, set()).add(
            (value.target.instance_id, value.target.generation)
        )

    def status(self, event):
        self.events.append(
            {"kind": event.kind, "message": event.message, "epoch": event.source_epoch}
        )

    def measure(self, started, limits):
        import torch

        self.durations.append(time.perf_counter() - started)
        self.peak_driver = max(self.peak_driver, torch.mps.driver_allocated_memory())
        self.peak_rss = max(
            self.peak_rss, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        )
        if (
            self.peak_driver > limits["driver_bytes"]
            or self.peak_rss > limits["rss_bytes"]
        ):
            raise MemoryError("Frozen resource budget exceeded")


class RecordedRaw:
    def __init__(self, raw, audit):
        self.raw, self.audit = raw, audit

    def detect(self, frames):
        result = self.raw.detect(frames)
        actual = [box_record(box) for box in result[SOURCE][-1].boxes]
        if self.audit.parity:
            second = int(self.audit.current["second"])
            if actual != self.audit.baseline[second]["raw_detector_boxes"]:
                raise AssertionError(f"Raw detector differs at {second}")
        self.audit.raw_calls += 1
        return result


class RecordedCutie:
    def __init__(self, runtime, audit):
        self.runtime, self.audit = runtime, audit

    def reset(self):
        self.runtime.reset()

    def step(self, image, **kwargs):
        actual = self.runtime.step(image, **kwargs)
        self.audit.steps += 1
        self.audit.seeds += bool(kwargs.get("object_ids"))
        if self.audit.parity and float(self.audit.current["second"]).is_integer():
            second = int(self.audit.current["second"])
            expected = cv2.imread(
                str(BASE / "masks" / f"{second}.png"), cv2.IMREAD_UNCHANGED
            )
            if not np.array_equal(actual.mask, expected):
                raise AssertionError(f"Mask differs at {second}")
            quality = [
                {
                    "track_id": item.object_id - 1,
                    "area": item.area,
                    "mean_probability": item.mean_probability,
                    "p10_probability": item.p10_probability,
                }
                for item in actual.objects
            ]
            if quality != self.audit.baseline[second]["objects"]:
                raise AssertionError(f"Quality differs at {second}")
            self.audit.masks_equal += 1
        return actual


def opened(stack, audit, output):
    config = YoloConfig(
        model=str(YOLO), confidence={"item": 0.4}, imgsz=640, iou=0.7, tracking=False
    )
    raw = stack.enter_context(
        open_detector(
            config, OnnxConfig(), (SOURCE,), "macos", InferenceOptions(native_mps=True)
        )
    )
    runtime = stack.enter_context(open_cutie(CUTIE, "mps"))
    control = LiveIdentityControl(
        "1" * 32,
        hashlib.sha256(SOURCE.encode()).hexdigest(),
        LiveIdentityState(),
        IdentityCatalog(output / "empty-catalog"),
        lambda _: None,
        clock=audit.clock if audit.parity else time.monotonic,
    )
    owner = ContinuousIdentityDetector(
        SOURCE,
        RecordedRaw(raw, audit),
        RecordedCutie(runtime, audit),
        control,
        startup_weights=SAM,
        label="item",
        publish_evidence=audit.evidence,
        report_status=audit.status,
        clock=audit.clock if audit.parity else time.monotonic,
    )
    stack.callback(owner.close)
    return owner, raw


def verify_result(audit, result):
    second = audit.current["second"]
    if second == 0 or not float(second).is_integer():
        if result or audit.emitted:
            raise AssertionError("Startup/halfstep unexpectedly published")
        return
    row = audit.baseline[int(second)]
    expected = eligible(row)
    if sorted(i for i, _ in audit.emitted) != expected:
        raise AssertionError(f"Eligibility differs at {second}")
    observation = result[SOURCE][-1]

    def geometry(box):
        return box.x1, box.y1, box.x2, box.y2, box.track_id - 1

    if [geometry(box) for box in observation.boxes] != [
        (box["x1"], box["y1"], box["x2"], box["y2"], box["track_id"])
        for box in row["boxes"]
    ]:
        raise AssertionError(f"Published geometry differs at {second}")
    probabilities = {
        item["track_id"] + 1: item["p10_probability"] for item in row["objects"]
    }
    if any(p != probabilities[i] for i, p in audit.emitted):
        raise AssertionError("Published quality differs")
    audit.observations.append({"second": second, "eligible_ids": expected})


def parity(owner, audit, limits):
    rows = json.loads((CLIP / "sampled.json").read_text())["rows"][:241]
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    owner.source_changed("a" * 32)
    try:
        for i, row in enumerate(rows):
            ok, image = capture.read()
            if not ok or pixels_hash(image) != row["pixels_sha256"]:
                raise ValueError("Source pixels changed")
            image.setflags(write=False)
            audit.current, audit.now, audit.emitted = row, 10 + row["second"], []
            frame = Frame(
                datetime(2026, 10, 3) + timedelta(seconds=row["second"]),
                image,
                CaptureStamp("a" * 32, i, audit.now),
            )
            tick = time.perf_counter()
            result = owner.detect({SOURCE: (frame,)})
            verify_result(audit, result)
            audit.measure(tick, limits)
    finally:
        capture.release()
    if (audit.steps, audit.raw_calls, audit.masks_equal, len(audit.observations)) != (
        241,
        121,
        121,
        120,
    ):
        raise AssertionError("Incomplete actual-model parity")


def produce(source, owner, stop, errors):
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    rows = json.loads((CLIP / "sampled.json").read_text())["rows"][:121]
    origin = time.monotonic()
    owner.source_changed("a" * 32)
    try:
        for i, row in enumerate(rows):
            if stop.wait(max(0, origin + i * 0.5 - time.monotonic())):
                return
            ok, image = capture.read()
            if not ok or pixels_hash(image) != row["pixels_sha256"]:
                raise ValueError("Paced source pixels changed")
            if i == 60:
                owner.source_changed(None)
            if 60 <= i < 64:
                continue
            epoch = ("a" if i < 60 else "b") * 32
            if i == 64:
                owner.source_changed(epoch)
            now = time.monotonic()
            value = CapturedFrame(
                Frame(datetime.now(), image, CaptureStamp(epoch, i, now))
            )
            source.publish(SOURCE, value, now)
    except BaseException as error:
        errors.append(f"{type(error).__name__}: {error}")
    finally:
        capture.release()
        # Give the worker the final sample before the explicit stop.
        stop.wait(0.5)
        owner.source_changed(None)
        source.close()


def paced(owner, audit, limits):
    # Inputs are already selected at 2Hz; interval0 avoids resampling jitter.
    source, stop, errors = (
        StreamSource((SOURCE,), retention=4, interval=0, width=1280),
        Event(),
        [],
    )
    thread = Thread(target=produce, args=(source, owner, stop, errors))
    thread.start()
    try:
        for batch in source.batches():
            tick = time.perf_counter()
            result = owner.detect(batch.frames)
            audit.measure(tick, limits)
            if result:
                observation = result[SOURCE][-1]
                if time.monotonic() - observation.capture.monotonic_at >= 1:
                    raise AssertionError("Paced output is stale")
                audit.observations.append(
                    {
                        "epoch": observation.capture.epoch,
                        "sequence": observation.capture.sequence,
                    }
                )
    finally:
        stop.set()
        thread.join()
        source.close()
    if errors:
        raise RuntimeError(errors[0])
    first, second = audit.epochs.get("a" * 32, set()), audit.epochs.get("b" * 32, set())
    if not first or not second or first & second or audit.seeds != 2:
        raise AssertionError("Startup loop or missing fresh reconnect generations")


def run(mode, protocol, output):
    import torch

    frozen = checked(protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual MPS required")
    torch.set_num_threads(2)
    output.mkdir(parents=True, exist_ok=False)
    baseline = {
        row["second"]: row
        for row in json.loads((BASE / "streaming.json").read_text())["timeline"]
        if row["second"] <= 120
    }
    audit = Audit(mode == "parity", baseline)
    report, start = (
        {
            "passed": False,
            "protocol_sha256": digest(protocol),
            "mode": mode,
            "error": None,
        },
        time.perf_counter(),
    )
    try:
        with ExitStack() as stack:
            owner, raw = opened(stack, audit, output)
            (parity if audit.parity else paced)(owner, audit, frozen["limits"])
            backend = raw.model.predictor.model
            report["backend"] = {
                "yolo_device": str(backend.device),
                "yolo_fp16": bool(backend.fp16),
                "cutie_device": "mps",
                "cutie_dtype": "float32",
            }
            if torch.device(backend.device).type != "mps" or not backend.fp16:
                raise AssertionError("Actual raw model backend changed")
            report["passed"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report.update(
            {
                "elapsed_seconds": time.perf_counter() - start,
                "steps": audit.steps,
                "raw_calls": audit.raw_calls,
                "seeds": audit.seeds,
                "integer_masks_equal": audit.masks_equal,
                "observations": audit.observations,
                "statuses": audit.events,
                "generation_sets": {
                    key: sorted(value) for key, value in audit.epochs.items()
                },
                "durations": audit.durations,
                "peak_driver_bytes": audit.peak_driver,
                "peak_rss_bytes": audit.peak_rss,
            }
        )
        write_json(output / "report.json", report)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key
                    not in ("observations", "statuses", "generation_sets", "durations")
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "parity", "paced"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.protocol.exists():
            parser.error("Preserve frozen recipes")
        freeze(args.protocol)
    else:
        run(args.mode, args.protocol, args.output)
