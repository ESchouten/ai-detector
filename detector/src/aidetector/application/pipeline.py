from aidetector.application.ports import (
    ObjectDetector,
    ObservationIdentifier,
    PublishObservation,
    SourceBatch,
    ignore_observation,
)
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.domain.events import EventAssembler
from aidetector.domain.models import DetectionEvent, Observation
from aidetector.domain.policy import EventPolicy

_DEFAULT_POLICY = EventPolicy()


class DetectionPipeline:
    """Turn source batches into completed events; one detector worker owns access."""

    def __init__(
        self,
        detector: ObjectDetector | None = None,
        policy: EventPolicy = _DEFAULT_POLICY,
        report_status: ReportStatus = ignore_status,
        publish_observation: PublishObservation = ignore_observation,
        *,
        identifier: ObservationIdentifier | None = None,
    ):
        self.detector = detector
        self.events = EventAssembler(policy)
        self.report_status = report_status
        self.publish_observation = publish_observation
        self.identifier = identifier

    def process(self, batch: SourceBatch) -> list[DetectionEvent]:
        if self.detector is None:
            snapshots = [
                DetectionEvent(
                    source,
                    (
                        Observation(
                            frames[-1].date,
                            frames[-1].image,
                            {},
                            capture=frames[-1].capture,
                        ),
                    ),
                )
                for source, frames in batch.frames.items()
            ]
            for event in snapshots:
                latest = event.observations[-1]
                self.publish_observation(event.source, latest)
                self.report_status(
                    StatusEvent(
                        "processed",
                        event.source,
                        source_epoch=latest.capture.epoch if latest.capture else None,
                    )
                )
            return snapshots
        completed: list[DetectionEvent] = []
        if batch.frames:
            for source, observations in self.detector.detect(batch.frames).items():
                latest = observations[-1]
                if self.identifier is not None:
                    # Context frames reuse the latest boxes; only this frame was inferred.
                    latest = self.identifier.identify(source, latest)
                    observations = (*observations[:-1], latest)
                self.publish_observation(source, latest)
                self.report_status(
                    StatusEvent(
                        "inference",
                        source,
                        source_epoch=latest.capture.epoch if latest.capture else None,
                    )
                )
                completed.extend(self.events.observe(source, observations))
        if batch.advance_to is not None:
            completed.extend(self.events.advance(batch.advance_to))
        for source in batch.finished_sources:
            completed.extend(self.events.finish(source))
        return completed

    def finish(self) -> list[DetectionEvent]:
        return self.events.finish()
