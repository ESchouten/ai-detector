from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Frame,
    Observation,
    ValidationResult,
)

Frames = Mapping[str, tuple[Frame, ...]]
PublishObservation = Callable[[str, Observation], None]


def ignore_observation(source: str, observation: Observation) -> None:
    pass


@dataclass(frozen=True)
class SourceBatch:
    """Frames, an optional event clock, and sources that reached EOF.

    Live inputs advance to their newest frame time, or wall time when idle.
    Finite inputs omit advance_to and progress only through media timestamps.
    The pipeline processes frames before advancing the clock and finishing sources.
    """

    frames: Frames
    advance_to: datetime | None = None
    finished_sources: tuple[str, ...] = ()


class SourceError(RuntimeError):
    pass


class ValidationUnavailable(RuntimeError):
    pass


class DeliveryError(RuntimeError):
    pass


class FrameSource(Protocol):
    """Yield nonempty, time-ordered frame tuples for each source in a batch.

    Images are borrowed read-only uint8 H×W×3 BGR arrays and remain valid after
    iteration advances.
    Empty batches can signal idle time or EOF. The caller closes the generator
    to release acquisition resources. Report expected input failures as SourceError.
    """

    def batches(self) -> Generator[SourceBatch, None, None]: ...

    def close(self) -> None:
        """Request stop and wake adapter-managed waits; repeated calls are safe.

        Native I/O may finish under its own timeout before iteration can stop.
        """
        ...


class ObjectDetector(Protocol):
    """Return nonempty, time-ordered observations for each input source.

    Keep source identities separate and preserve borrowed input images.
    Returned images and confidence mappings are read-only to their consumers.
    """

    def detect(self, frames: Frames) -> dict[str, tuple[Observation, ...]]: ...


class EventValidator(Protocol):
    """Verify an event without changing it.

    Raise ValidationUnavailable for expected verification failures. Unexpected
    exceptions propagate to supervision rather than becoming an ordinary rejection.
    """

    def validate(self, event: DetectionEvent) -> ValidationResult: ...


class EventExporter(Protocol):
    """Deliver a result without changing the event or its borrowed data.

    Raise DeliveryError for expected delivery failures. The application attempts
    independent destinations before propagating an unexpected exception.
    """

    def export(self, result: EventResult) -> None: ...


class HealthMonitor(Protocol):
    """The runtime owns execution and joining; unexpected failures leave run().

    Repeated stop calls wake interval waits without joining or interrupting a
    request already in progress. That request retains its configured timeout.
    """

    def run(self) -> None: ...

    def stop(self) -> None: ...
