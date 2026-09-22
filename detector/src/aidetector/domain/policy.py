from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    ValidationResult,
    ValidationStatus,
)

ConfidenceThreshold = float | dict[str, float]


def confidence_matches(
    confidence: Mapping[str, float], threshold: ConfidenceThreshold | None
) -> bool:
    if threshold is None:
        return True
    if isinstance(threshold, dict):
        return any(
            name in threshold and score >= threshold[name]
            for name, score in confidence.items()
        )
    return max(confidence.values(), default=0.0) >= threshold


@dataclass(frozen=True)
class EventPolicy:
    min_frames: int = 3
    max_duration: float = 60
    inactivity_timeout: float = 5
    trailing_time: float = 1


@dataclass(frozen=True)
class ExportPolicy:
    confidence: ConfidenceThreshold | None = None
    export_rejected: bool = False
    archive_failed_validation: bool = False

    def accepts(self, event: DetectionEvent, validation: ValidationResult) -> bool:
        if not confidence_matches(event.best.confidence, self.confidence):
            return False
        if validation.status is ValidationStatus.FAILED:
            return self.archive_failed_validation
        if validation.status is ValidationStatus.REJECTED:
            return self.export_rejected
        return True


class Cooldown:
    def __init__(self, seconds: float | dict[str, float] = 0):
        self.seconds = seconds
        self._last_accepted: dict[tuple[str, str], datetime] = {}

    def allows(self, event: DetectionEvent) -> bool:
        best = event.best
        if not best.confidence:
            return True
        for name in best.confidence:
            previous = self._last_accepted.get((event.source, name))
            duration = (
                self.seconds.get(name, 0)
                if isinstance(self.seconds, dict)
                else self.seconds
            )
            if previous is None or (best.date - previous).total_seconds() >= duration:
                return True
        return False

    def record(self, result: EventResult) -> None:
        """Only approved or deliberately unvalidated outcomes consume cooldown."""
        if result.validation.status not in (
            ValidationStatus.APPROVED,
            ValidationStatus.UNVALIDATED,
        ):
            return
        event = result.event
        best = event.best
        for name in best.confidence:
            self._last_accepted[event.source, name] = best.date
