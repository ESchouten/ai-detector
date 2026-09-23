from aidetector.application.ports import (
    ObjectDetector,
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
    ):
        self.detector = detector
        self.events = EventAssembler(policy)
        self.report_status = report_status
        self.publish_observation = publish_observation

    def process(self, batch: SourceBatch) -> list[DetectionEvent]:
        if self.detector is None:
            snapshots = [
                DetectionEvent(
                    source, (Observation(frames[-1].date, frames[-1].image, {}),)
                )
                for source, frames in batch.frames.items()
            ]
            for event in snapshots:
                self.publish_observation(event.source, event.observations[-1])
                self.report_status(StatusEvent("processed", event.source))
            return snapshots
        completed: list[DetectionEvent] = []
        if batch.frames:
            for source, observations in self.detector.detect(batch.frames).items():
                self.publish_observation(source, observations[-1])
                self.report_status(StatusEvent("inference", source))
                completed.extend(self.events.observe(source, observations))
        if batch.advance_to is not None:
            completed.extend(self.events.advance(batch.advance_to))
        for source in batch.finished_sources:
            completed.extend(self.events.finish(source))
        return completed

    def finish(self) -> list[DetectionEvent]:
        return self.events.finish()
