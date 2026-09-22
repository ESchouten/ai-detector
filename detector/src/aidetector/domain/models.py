from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True)
class BoundingBox:
    """Image-space bounds, optionally labeled by object detection."""

    x1: int
    y1: int
    x2: int
    y2: int
    label: str | None = None
    confidence: float | None = None

    @classmethod
    def enclosing(cls, boxes: Sequence[BoundingBox]) -> BoundingBox | None:
        if not boxes:
            return None
        return cls(
            min(box.x1 for box in boxes),
            min(box.y1 for box in boxes),
            max(box.x2 for box in boxes),
            max(box.y2 for box in boxes),
        )


@dataclass(frozen=True)
class Frame:
    """Source timestamp and borrowed read-only uint8 H×W×3 BGR pixels."""

    date: datetime
    image: NDArray[np.uint8]


@dataclass(frozen=True)
class Observation:
    """A frame with class scores and display boxes; context may be unscored.

    Image pixels follow Frame's borrowed read-only uint8 H×W×3 BGR contract.
    Class scores are also borrowed read-only.
    """

    date: datetime
    image: NDArray[np.uint8]
    confidence: Mapping[str, float]
    boxes: tuple[BoundingBox, ...] = ()

    @property
    def enclosing_box(self) -> BoundingBox | None:
        return BoundingBox.enclosing(self.boxes)

    @property
    def score(self) -> float:
        return max(self.confidence.values(), default=0.0)


@dataclass(frozen=True)
class DetectionEvent:
    """A completed, nonempty sequence from one source, ordered by source time."""

    source: str
    observations: tuple[Observation, ...]

    @property
    def best(self) -> Observation:
        return max(self.observations, key=lambda observation: observation.score)

    @property
    def start(self) -> datetime:
        return self.observations[0].date

    @property
    def end(self) -> datetime:
        return self.observations[-1].date

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds()


class ValidationStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    UNVALIDATED = "unvalidated"
    FAILED = "failed"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    error: str | None = None

    @property
    def validated(self) -> bool | None:
        if self.status is ValidationStatus.APPROVED:
            return True
        if self.status is ValidationStatus.REJECTED:
            return False
        return None


@dataclass(frozen=True)
class EventResult:
    """An event and its verification outcome, independent of delivery."""

    event: DetectionEvent
    validation: ValidationResult
