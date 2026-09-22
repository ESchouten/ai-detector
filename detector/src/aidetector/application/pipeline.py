from aidetector.application.ports import ObjectDetector, SourceBatch
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
    ):
        self.detector = detector
        self.events = EventAssembler(policy)

    def process(self, batch: SourceBatch) -> list[DetectionEvent]:
        if self.detector is None:
            return [
                DetectionEvent(
                    source, (Observation(frames[-1].date, frames[-1].image, {}),)
                )
                for source, frames in batch.frames.items()
            ]
        completed: list[DetectionEvent] = []
        if batch.frames:
            for source, observations in self.detector.detect(batch.frames).items():
                completed.extend(self.events.observe(source, observations))
        if batch.advance_to is not None:
            completed.extend(self.events.advance(batch.advance_to))
        for source in batch.finished_sources:
            completed.extend(self.events.finish(source))
        return completed

    def finish(self) -> list[DetectionEvent]:
        return self.events.finish()
