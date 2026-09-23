"""Controlled input for the CLI's real process/signal lifecycle test."""

import sys
from datetime import datetime
from pathlib import Path
from threading import Event

import numpy as np

from aidetector import bootstrap
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import DeliveryError, SourceBatch
from aidetector.cli import main
from aidetector.domain.models import Frame, Observation
from aidetector.domain.policy import Cooldown, EventPolicy, ExportPolicy
from aidetector.runtime import DetectorWorker, run_detectors


class HoldingSource:
    def __init__(self):
        self.stopped = Event()

    def batches(self):
        yield SourceBatch(
            {"camera": (Frame(datetime.now(), np.zeros((8, 8, 3), dtype=np.uint8)),)}
        )
        Path("ready").touch()
        if not self.stopped.wait(10):
            raise TimeoutError("The test did not request shutdown")

    def close(self):
        self.stopped.set()


class Detector:
    def detect(self, frames):
        frame = frames["camera"][0]
        return {"camera": (Observation(frame.date, frame.image, {"cow": 0.9}),)}


class Exporter:
    def export(self, result):
        Path("flushed").write_text(result.validation.status.value)
        if sys.argv[1] == "failure":
            raise DeliveryError("Delivery failed during shutdown")


class Health:
    def __init__(self):
        self.stopped = Event()

    def run(self):
        assert self.stopped.wait(10), "Health monitor was not stopped by the signal"
        Path("health-stopped").touch()

    def stop(self):
        self.stopped.set()


def run(
    config,
    config_directory,
    data_directory,
    stop_requested=None,
    report_status=None,
    live_preview=False,
):
    worker = DetectorWorker(
        HoldingSource(),
        DetectionPipeline(Detector(), EventPolicy(min_frames=1)),
        EventDelivery(
            (Destination("archive", Exporter(), ExportPolicy()),), Cooldown()
        ),
    )
    return run_detectors((worker,), Health(), stop_requested)


bootstrap.run_application = run
raise SystemExit(main(["--config", "config.json", *sys.argv[2:]]))
