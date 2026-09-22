from contextlib import ExitStack
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.exporters.telegram import TelegramExporter
from aidetector.adapters.exporters.webhook import WebhookExporter
from aidetector.adapters.health import Healthcheck
from aidetector.adapters.inference.model_assets import resolve_model_path
from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.sources.files import FileSource
from aidetector.adapters.sources.streams import StreamPool, StreamSource
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import EventValidator, ObjectDetector
from aidetector.configuration import Config, ExportersConfig, SourceConfig, source_kind
from aidetector.domain.policy import Cooldown, EventPolicy, ExportPolicy
from aidetector.runtime import DetectorWorker, RunStats, run_detectors
from aidetector.version import TYPE


def build_source(
    settings: SourceConfig, directory: Path, streams: StreamPool
) -> FileSource | StreamSource:
    if source_kind(settings.source[0]) != "stream":
        sources = tuple(
            source
            if urlsplit(source).scheme in {"http", "https"}
            else str((directory / Path(source).expanduser()).resolve())
            for source in settings.source
        )
        return FileSource(
            sources, width=settings.frames_width, interval=settings.interval
        )
    return streams.subscribe(
        settings.source,
        width=settings.frames_width,
        retention=settings.frame_retention,
        interval=settings.interval,
    )


def build_destinations(
    config: ExportersConfig, directory: Path, media: EventMedia
) -> tuple[Destination, ...]:
    destinations: list[Destination] = []
    for index, settings in enumerate(config.disk):
        destinations.append(
            Destination(
                f"disk-{index + 1}",
                DiskExporter(settings, directory / "detections", media),
                ExportPolicy(
                    settings.confidence,
                    settings.export_rejected,
                    archive_failed_validation=True,
                ),
            )
        )
    for index, settings in enumerate(config.telegram):
        destinations.append(
            Destination(
                f"telegram-{index + 1}",
                TelegramExporter(settings, media),
                ExportPolicy(settings.confidence, settings.export_rejected),
            )
        )
    for index, settings in enumerate(config.webhook):
        destinations.append(
            Destination(
                f"webhook-{index + 1}",
                WebhookExporter(settings, media),
                ExportPolicy(settings.confidence, settings.export_rejected),
            )
        )
    return tuple(destinations)


def run_application(
    config: Config,
    config_directory: Path,
    data_directory: Path,
    stop_requested: Event | None = None,
) -> tuple[RunStats, ...]:
    """Construct workers and own their shared captures, models and providers."""
    models = tuple(
        ModelRequirements(
            settings.yolo.model, settings.yolo.imgsz, len(settings.detection.source)
        )
        for settings in config.detectors
        if settings.yolo is not None
    )
    with ExitStack() as resources:
        options = resources.enter_context(inference_runtime(config.onnx, models, TYPE))
        streams = StreamPool()
        workers: list[DetectorWorker] = []
        for index, settings in enumerate(config.detectors, start=1):
            source = build_source(settings.detection, config_directory, streams)
            resources.callback(source.close)
            detector: ObjectDetector | None = None
            event_policy = EventPolicy()
            if settings.yolo is not None:
                from aidetector.adapters.inference.yolo import open_detector

                model_settings = settings.yolo.model_copy(
                    update={
                        "model": resolve_model_path(
                            settings.yolo.model,
                            config_directory,
                            data_directory / "models",
                        )
                    }
                )
                detector = resources.enter_context(
                    open_detector(
                        model_settings,
                        config.onnx,
                        source.sources,
                        TYPE,
                        options,
                    )
                )
                event_policy = EventPolicy(
                    min_frames=settings.yolo.frames_min,
                    max_duration=settings.yolo.time_max,
                    inactivity_timeout=settings.yolo.timeout,
                    trailing_time=settings.yolo.include_trailing_time,
                )
            media = EventMedia()
            validator: EventValidator | None = None
            if settings.vlm:
                from aidetector.adapters.vlm import VlmValidator

                validator = VlmValidator(settings.vlm, media)
            cooldown = Cooldown(
                settings.yolo.cooldown if settings.yolo is not None else 0
            )
            pipeline = DetectionPipeline(detector, event_policy)
            delivery = EventDelivery(
                build_destinations(settings.exporters, data_directory, media),
                cooldown,
                validator,
            )
            workers.append(
                DetectorWorker(
                    source,
                    pipeline,
                    delivery,
                    pending_events=settings.pending_events,
                    name=f"detector-{index}",
                )
            )
        health = Healthcheck(config.health) if config.health is not None else None
        resources.enter_context(streams.open())
        return run_detectors(tuple(workers), health, stop_requested)
