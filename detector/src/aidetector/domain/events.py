from dataclasses import dataclass
from datetime import datetime

from aidetector.domain.models import DetectionEvent, Observation
from aidetector.domain.policy import EventPolicy


@dataclass
class _Window:
    observations: list[Observation]
    first_match: datetime
    last_match: datetime
    matches: int


class EventAssembler:
    """Own event windows; callers supply source time and serialize access."""

    def __init__(self, policy: EventPolicy):
        self.policy = policy
        self._windows: dict[str, _Window] = {}

    def observe(
        self, source: str, observations: tuple[Observation, ...]
    ) -> list[DetectionEvent]:
        events: list[DetectionEvent] = []
        context: list[Observation] = []
        for observation in observations:
            # Expire first so an observation at the boundary starts the next window.
            events.extend(self._expire(source, observation.date))
            window = self._windows.get(source)
            if window is None:
                context.append(observation)
                if observation.confidence:
                    self._windows[source] = _Window(
                        context, observation.date, observation.date, 1
                    )
                    context = []
                continue
            if observation.date <= window.observations[-1].date:
                continue
            if observation.confidence:
                window.last_match = observation.date
                window.matches += 1
                window.observations.append(observation)
            elif (
                observation.date - window.last_match
            ).total_seconds() <= self.policy.trailing_time:
                window.observations.append(observation)
        return events

    def advance(self, now: datetime) -> list[DetectionEvent]:
        events: list[DetectionEvent] = []
        for source in tuple(self._windows):
            events.extend(self._expire(source, now))
        return events

    def finish(self, source: str | None = None) -> list[DetectionEvent]:
        events: list[DetectionEvent] = []
        sources = tuple(self._windows) if source is None else (source,)
        for name in sources:
            if name in self._windows:
                events.extend(self._close(name))
        return events

    def _expire(self, source: str, now: datetime) -> list[DetectionEvent]:
        window = self._windows.get(source)
        if window is None:
            return []
        duration = (now - window.first_match).total_seconds()
        inactivity = (now - window.last_match).total_seconds()
        if duration >= self.policy.max_duration or (
            self.policy.inactivity_timeout > 0
            and inactivity >= self.policy.inactivity_timeout
        ):
            return self._close(source)
        return []

    def _close(self, source: str) -> list[DetectionEvent]:
        window = self._windows.pop(source)
        if window.matches >= self.policy.min_frames:
            return [DetectionEvent(source, tuple(window.observations))]
        return []
