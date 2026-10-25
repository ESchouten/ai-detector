from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Observation,
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
    def __init__(self, seconds: float | dict[str, float] = 0, *, min_frames: int = 1):
        self.seconds = seconds
        self.min_frames = min_frames
        self._last_accepted: dict[tuple[str, str], datetime] = {}

    def _outside(self, source: str, name: str, date: datetime) -> bool:
        previous = self._last_accepted.get((source, name))
        duration = (
            self.seconds.get(name, 0)
            if isinstance(self.seconds, dict)
            else self.seconds
        )
        return previous is None or (date - previous).total_seconds() >= duration

    def allows(self, event: DetectionEvent) -> bool:
        if not any(observation.confidence for observation in event.observations):
            return True
        return (
            sum(
                any(
                    self._outside(event.source, name, observation.date)
                    for name in observation.confidence
                )
                for observation in event.observations
            )
            >= self.min_frames
        )

    def record(self, result: EventResult) -> None:
        """Only approved or deliberately unvalidated outcomes consume cooldown."""
        if result.validation.status not in (
            ValidationStatus.APPROVED,
            ValidationStatus.UNVALIDATED,
        ):
            return
        event = result.event
        best: dict[str, Observation] = {}
        for observation in event.observations:
            for name, score in observation.confidence.items():
                candidate = best.get(name)
                if self._outside(event.source, name, observation.date) and (
                    candidate is None or score > candidate.confidence[name]
                ):
                    best[name] = observation
        # Decide against the old cooldowns before updating any class in this event.
        for name, observation in best.items():
            self._last_accepted[event.source, name] = observation.date
