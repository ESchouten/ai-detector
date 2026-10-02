import logging
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from aidetector.adapters.diagnostics import log_detector_configuration
from aidetector.adapters.exporters.disk import DiskExporter
from aidetector.adapters.exporters.telegram import TelegramExporter
from aidetector.adapters.exporters.webhook import WebhookExporter
from aidetector.adapters.health import Healthcheck
from aidetector.adapters.inference.model_assets import resolve_model_path
from aidetector.adapters.inference.onnx import ModelRequirements, inference_runtime
from aidetector.adapters.live_preview import LivePreview
from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.sources.files import FileSource
from aidetector.adapters.sources.streams import StreamPool, StreamSource
from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.pipeline import DetectionPipeline
from aidetector.application.ports import (
    EventValidator,
    ObjectDetector,
    ignore_observation,
)
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.configuration import Config, ExportersConfig, SourceConfig, source_kind
from aidetector.domain.policy import Cooldown, EventPolicy, ExportPolicy
from aidetector.runtime import DetectorWorker, RunStats, run_detectors
from aidetector.version import TYPE

logger = logging.getLogger(__name__)


def _rule_reporter(report_status: ReportStatus, rule_id: str) -> ReportStatus:
    def report(event: StatusEvent) -> None:
        if event.kind in {"preparing", "preparation_failed", "notice"}:
            logger.log(
                logging.ERROR if event.kind == "preparation_failed" else logging.INFO,
                "%s: %s",
                rule_id,
                event.message,
            )
        report_status(replace(event, rule_id=rule_id))

    return report


def build_source(
    settings: SourceConfig,
    directory: Path,
    streams: StreamPool,
    report_status: ReportStatus = ignore_status,
) -> FileSource | StreamSource:
    if source_kind(settings.source[0]) != "stream":
        return FileSource(
            _resolved_sources(settings, directory),
            width=settings.frames_width,
            interval=settings.interval,
            report_status=report_status,
        )
    return streams.subscribe(
        settings.source,
        width=settings.frames_width,
        retention=settings.frame_retention,
        interval=settings.interval,
    )


def _resolved_sources(settings: SourceConfig, directory: Path) -> tuple[str, ...]:
    if source_kind(settings.source[0]) == "stream":
        return settings.source
    return tuple(
        source
        if urlsplit(source).scheme in {"http", "https"}
        else str((directory / Path(source).expanduser()).resolve())
        for source in settings.source
    )


def build_destinations(
    config: ExportersConfig,
    directory: Path,
    media: EventMedia,
    report_status: ReportStatus = ignore_status,
) -> tuple[Destination, ...]:
    destinations: list[Destination] = []
    for index, settings in enumerate(config.disk):
        destinations.append(
            Destination(
                f"disk-{index + 1}",
                DiskExporter(
                    settings,
                    directory / "detections",
                    media,
                    report_status,
                    f"disk-{index + 1}",
                ),
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
    report_status: ReportStatus = ignore_status,
    live_preview: bool = False,
    prefer_tensorrt: bool = False,
) -> tuple[RunStats, ...]:
    """Construct workers and own their shared captures, models and providers."""
    for index, settings in enumerate(config.detectors, start=1):
        log_detector_configuration(
            index, settings, _resolved_sources(settings.detection, config_directory)
        )
    models = tuple(
        ModelRequirements(
            settings.yolo.model, settings.yolo.imgsz, len(settings.detection.source)
        )
        for settings in config.detectors
        if settings.yolo is not None
    )
    with ExitStack() as resources:
        report_status(
            StatusEvent("preparing", message="Preparing detection on this computer…")
        )
        options = resources.enter_context(
            inference_runtime(config.onnx, models, TYPE, report_status)
        )
        engines = None
        if prefer_tensorrt and TYPE == "cuda":
            from aidetector.adapters.inference.prepared_engines import EnginePreparation

            engines = EnginePreparation(
                data_directory / "models" / "prepared", stop_requested, report_status
            )
        streams = StreamPool(report_status)
        preview = LivePreview(data_directory / "live") if live_preview else None
        workers: list[DetectorWorker] = []
        for index, settings in enumerate(config.detectors, start=1):
            logger.info(
                "Preparing detector-%d: %d source(s), %.2fs sampling interval, object detection %s",
                index,
                len(settings.detection.source),
                settings.detection.interval,
                "enabled" if settings.yolo is not None else "disabled",
            )
            rule_status = _rule_reporter(report_status, f"detector-{index}")
            source = build_source(
                settings.detection, config_directory, streams, report_status
            )
            resources.callback(source.close)
            detector: ObjectDetector | None = None
            event_policy = EventPolicy()
            if settings.yolo is not None:
                from aidetector.adapters.inference.yolo import open_detector

                report_status(
                    StatusEvent(
                        "preparing",
                        message=f"Opening detection rule {index}…",
                    )
                )
                model_settings = settings.yolo.model_copy(
                    update={
                        "model": resolve_model_path(
                            settings.yolo.model,
                            config_directory,
                            data_directory / "models",
                            rule_status,
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
                        cache_directory=data_directory / "models" / "prepared",
                        report_status=rule_status,
                        engines=engines,
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
            if settings.active_vlm:
                from aidetector.adapters.vlm import VlmValidator

                validator = VlmValidator(settings.active_vlm, media)
            cooldown = Cooldown(
                settings.yolo.cooldown if settings.yolo is not None else 0
            )
            publish = (
                preview.observer(f"detector-{index}", source.sources)
                if preview is not None
                else ignore_observation
            )
            pipeline = DetectionPipeline(detector, event_policy, rule_status, publish)
            delivery = EventDelivery(
                build_destinations(
                    settings.exporters, data_directory, media, rule_status
                ),
                cooldown,
                validator,
                rule_status,
            )
            logger.info(
                "Detector-%d ready: validation %s; destinations: %s",
                index,
                "enabled" if validator is not None else "disabled",
                ", ".join(destination.name for destination in delivery.destinations)
                or "none",
            )
            workers.append(
                DetectorWorker(
                    source,
                    pipeline,
                    delivery,
                    pending_events=settings.pending_events,
                    name=f"detector-{index}",
                    report_status=rule_status,
                )
            )
        health = Healthcheck(config.health) if config.health is not None else None
        if preview is not None:
            resources.enter_context(preview.open())
        resources.enter_context(streams.open())
        report_status(StatusEvent("ready"))
        if engines is not None:
            resources.enter_context(engines.running())
        return run_detectors(tuple(workers), health, stop_requested)
