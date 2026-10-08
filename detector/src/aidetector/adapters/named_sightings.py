"""What identity rules recognised on each camera, for the events of other rules."""

from collections import deque
from datetime import timedelta
from threading import Lock

from aidetector.domain.identity import Region, Sighting, individuals_in_event
from aidetector.domain.models import (
    BoundingBox,
    DetectionEvent,
    IdentityMatch,
    Observation,
)


def _region(box: BoundingBox, observation: Observation) -> Region:
    height, width = observation.image.shape[:2]
    return (box.x1 / width, box.y1 / height, box.x2 / width, box.y2 / height)


class NamedSightings:
    """Who was recognised where, kept briefly so that another rule's event can be named.

    A rule that detects behaviour, such as mounting, boxes the scene and not
    the animals in it. The rule that recognises individuals on the same camera
    records them here, and an event takes the individuals whose boxes lay
    inside its own while it lasted. Detector workers record and delivery
    workers read.
    """

    def __init__(self, keep: float = 600, apart: float = 1):
        self.keep = timedelta(seconds=keep)
        # Rules sample one camera at different moments; an animal has not
        # moved far in a second.
        self.apart = timedelta(seconds=apart)
        self._sightings: dict[str, deque[Sighting]] = {}
        self._lock = Lock()

    def record(self, source: str, observation: Observation) -> None:
        recognised = [
            Sighting(observation.date, box.identity, _region(box, observation))
            for box in observation.boxes
            if box.identity is not None and box.identity.identity_id is not None
        ]
        with self._lock:
            kept = self._sightings.setdefault(source, deque())
            kept.extend(recognised)
            while kept and observation.date - kept[0].at > self.keep:
                kept.popleft()

    def named(self, event: DetectionEvent) -> tuple[IdentityMatch, ...]:
        moments = [
            (
                observation.date,
                [_region(box, observation) for box in observation.boxes],
            )
            for observation in event.observations
            if observation.confidence and observation.boxes
        ]
        with self._lock:
            nearby = [
                sighting
                for sighting in self._sightings.get(event.source, ())
                if event.start - self.apart <= sighting.at <= event.end + self.apart
            ]
        return individuals_in_event(moments, nearby, apart=self.apart.total_seconds())
