"""Real bootstrap/worker/continuity/storage with explicit model and camera boundaries."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError

import numpy as np
import pytest

from aidetector.adapters.identity_profile_collector import IdentityProfileCollector
from aidetector.adapters.inference.continuous_identity import ContinuousIdentityDetector
from aidetector.adapters.inference.continuous_models import ContinuousModels
from aidetector.adapters.inference.cutie_runtime import CutieOutput, MaskEvidence
from aidetector.adapters.inference.identity_masks import select_startup_masks
from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.application.ports import SourceBatch
from aidetector.application.status import StatusEvent
from aidetector.bootstrap import run_application
from aidetector.configuration import Config
from aidetector.domain.models import BoundingBox, CaptureStamp, Frame, Observation


def configuration():
    return Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "0", "interval": 9, "frame_retention": 1},
                    "yolo": {"model": "model.pt", "frames_min": 1},
                    "identity": {"mode": "continuous", "labels": ["cow"]},
                }
            ]
        }
    )


@pytest.fixture
def inference(monkeypatch):
    @contextmanager
    def runtime(*args):
        yield InferenceOptions(native_mps=True, half=True)

    monkeypatch.setattr("aidetector.bootstrap.inference_runtime", runtime)
    return runtime


def test_missing_optional_runtime_fails_before_model_transfer(
    tmp_path, monkeypatch, inference
):
    def missing(package):
        assert package == "cutie"
        raise PackageNotFoundError(package)

    def unexpected(*args, **kwargs):
        raise AssertionError("No detection model should be opened or downloaded")

    monkeypatch.setattr("aidetector.adapters.inference.cutie_runtime.version", missing)
    monkeypatch.setattr("aidetector.bootstrap.resolve_model_path", unexpected)
    with pytest.raises(RuntimeError, match="source-install-only"):
        run_application(configuration(), tmp_path, tmp_path)
    assert not (tmp_path / "models").exists()


def test_unsupported_execution_does_not_silently_use_a_different_tracker(
    tmp_path, monkeypatch
):
    @contextmanager
    def runtime(*args):
        yield InferenceOptions()

    monkeypatch.setattr("aidetector.bootstrap.inference_runtime", runtime)
    with pytest.raises(RuntimeError, match="native MPS"):
        run_application(configuration(), tmp_path, tmp_path)


@pytest.mark.parametrize(
    "label, classes", [("typo", {0: ("cow", 0.8)}), ("cow", {1: ("horse", 0.8)})]
)
def test_continuous_label_must_be_in_the_loaded_models_configured_classes(
    tmp_path, monkeypatch, inference, label, classes
):
    opened = []

    class Raw:
        def __init__(self):
            self.classes = classes

    @contextmanager
    def open_raw(*args, **kwargs):
        try:
            yield Raw()
        finally:
            opened.append("raw-closed")

    monkeypatch.setattr("aidetector.adapters.inference.yolo.open_detector", open_raw)
    value = configuration().model_dump(by_alias=True)
    value["detectors"][0]["identity"]["labels"] = [label]
    with pytest.raises(ValueError, match="configured classes"):
        run_application(Config.model_validate(value), tmp_path, tmp_path)
    assert opened == ["raw-closed"]
    assert not (tmp_path / "models" / "continuous").exists()


class Source:
    def __init__(self, report, sources, clock, image, resources):
        self.report, self.sources = report, sources
        self.clock, self.image, self.resources = clock, image, resources

    def batches(self):
        for epoch, begin in (("a" * 32, 10.0), ("b" * 32, 30.0)):
            self.report(StatusEvent("source_epoch", "0", source_epoch=epoch))
            for index in range(13):
                self.clock[0] = begin + index * 0.5
                if index == 4:
                    self.report(StatusEvent("offline", "unrelated-camera"))
                frame = Frame(
                    datetime(2026, 1, 1) + timedelta(seconds=self.clock[0]),
                    self.image,
                    CaptureStamp(epoch, index, self.clock[0]),
                )
                yield SourceBatch({"0": (frame,)}, frame.date)
            self.clock[0] += 2
            self.report(StatusEvent("offline", "0"))
            yield SourceBatch({})

    def close(self):
        self.resources.append("subscription-close")


class Tracker:
    def __init__(self, resources):
        self.resources = resources
        self.mask = None

    def step(self, pixels, *, mask=None, object_ids=()):
        if mask is not None:
            self.mask = mask
        assert self.mask is not None
        return CutieOutput(self.mask, (MaskEvidence(1, 10000, 0.9, 0.9),))

    def reset(self):
        self.resources.append("tracking-reset")
        self.mask = None


@pytest.mark.parametrize("storage_available", [True, False])
def test_unenrolled_continuous_application_keeps_tracking_with_optional_storage(
    tmp_path, monkeypatch, inference, storage_available
):
    clock = [10.0]
    resources, startup, subscriptions, statuses = [], [], [], []
    image = np.zeros((128, 128, 3), np.uint8)
    image.flags.writeable = False
    box = BoundingBox(10, 10, 110, 110, "cow", 0.9)
    if not storage_available:
        (tmp_path / "identities").mkdir()
        (tmp_path / "identities" / "automatic").write_text("unavailable directory")

    class Raw:
        classes = {0: ("cow", 0.9)}

        def detect(self, frames):
            frame = frames["0"][-1]
            return {
                "0": (
                    Observation(
                        frame.date, frame.image, {"cow": 0.9}, (box,), frame.capture
                    ),
                )
            }

    @contextmanager
    def open_raw(settings, *args, **kwargs):
        assert not settings.tracking
        resources.append("raw-open")
        try:
            yield Raw()
        finally:
            resources.append("raw-close")

    @contextmanager
    def open_tracker(*args):
        resources.append("cutie-open")
        try:
            yield Tracker(resources)
        finally:
            resources.append("cutie-close")

    def segment(weights, pixels, boxes):
        startup.append(clock[0])
        masks = np.zeros((1, 128, 128), bool)
        masks[0, 10:110, 10:110] = True
        return select_startup_masks(masks, boxes)

    class Pool:
        def __init__(self, report):
            self.report = report

        def subscribe(self, sources, **kwargs):
            subscriptions.append(kwargs)
            return Source(self.report, sources, clock, image, resources)

        @contextmanager
        def open(self):
            resources.append("capture-open")
            try:
                yield self
            finally:
                resources.append("capture-close")

    monkeypatch.setattr("aidetector.bootstrap.StreamPool", Pool)
    monkeypatch.setattr("aidetector.adapters.inference.yolo.open_detector", open_raw)
    monkeypatch.setattr(
        "aidetector.adapters.inference.cutie_runtime.open_cutie", open_tracker
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.continuous_models.prepare_continuous_models",
        lambda *args: ContinuousModels(tmp_path / "cutie.pth", tmp_path / "sam.pt"),
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.continuous_identity.segment_startup", segment
    )
    monkeypatch.setattr(
        "aidetector.adapters.inference.continuous_identity.ContinuousIdentityDetector",
        lambda *args, **kwargs: ContinuousIdentityDetector(
            *args, **kwargs, clock=lambda: clock[0]
        ),
    )
    monkeypatch.setattr(
        "aidetector.adapters.identity_profile_collector.IdentityProfileCollector",
        lambda *args, **kwargs: IdentityProfileCollector(
            *args, **kwargs, clock=lambda: clock[0]
        ),
    )

    config = configuration()
    result = run_application(config, tmp_path, tmp_path, report_status=statuses.append)
    assert result[0].events > 0
    assert not result[0].failed
    assert subscriptions == [{"width": 1280, "retention": 4, "interval": 0.5}]
    assert config.detectors[0].detection.interval == 9
    assert config.detectors[0].detection.frame_retention == 1
    assert startup == [
        10,
        30,
    ]  # unrelated camera disconnection cannot reset this camera
    assert (
        resources.index("capture-close")
        < resources.index("cutie-close")
        < resources.index("raw-close")
    )
    assert {event.source_epoch for event in statuses if event.kind == "inference"} == {
        "a" * 32,
        "b" * 32,
    }
    assert_profiles(tmp_path, statuses, storage_available)


def assert_profiles(directory, statuses, storage_available):
    assert not (directory / "identities" / "catalog.json").exists()
    assert not (directory / "identities" / "embeddings.sqlite").exists()
    if not storage_available:
        assert len([event for event in statuses if event.kind == "notice"]) == 1
        assert (directory / "identities" / "automatic").is_file()
        return
    with sqlite3.connect(
        directory / "identities" / "automatic" / "profiles.sqlite"
    ) as db:
        facts = [
            json.loads(row[0]) for row in db.execute("SELECT facts FROM candidates")
        ]
    assert len(facts) == 2
    assert facts[0]["episode_id"] != facts[1]["episode_id"]
