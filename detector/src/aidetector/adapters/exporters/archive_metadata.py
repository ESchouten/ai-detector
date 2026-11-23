from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aidetector.application.ports import camera_id
from aidetector.domain.models import EventResult


class CropMetadata(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class CandidateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float


class IndividualMetadata(BaseModel):
    """A tracked object of the event and the named individuals it resembles most."""

    model_config = ConfigDict(extra="forbid")

    track: int
    label: str
    # The sighting under individuals/sightings/ that holds this track's pictures.
    sighting: str = Field(pattern=r"^[a-f0-9]{32}$")
    # Set when the best candidate cleared the installation's naming threshold.
    name: str | None
    candidates: list[CandidateMetadata]


class ManualReview(BaseModel):
    """A person's verdict on the event, from the web application or Telegram."""

    model_config = ConfigDict(extra="forbid")

    validated: bool
    source: Literal["web", "telegram"]
    reviewed_at: str


class EventMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    event_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    # The camera's 12-character ID, as in the logs; never its address.
    camera: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")
    validated: bool | None
    confidence: float = Field(ge=0, le=1)
    confidences: dict[str, float]
    detections: int = Field(ge=1)
    start: str
    end: str
    duration: float = Field(ge=0)
    crop: CropMetadata | None = None
    validation_error: str | None = None
    # Absent when individuals are not recognised for this event.
    individuals: list[IndividualMetadata] | None = None
    individuals_error: str | None = None
    # The web application adds this to a published metadata.json when someone reviews
    # the event, leaving `validated` as the validator's own result. The detector
    # describes it here for the shared schema and never writes it.
    review: ManualReview | None = Field(default=None, exclude=True)

    @classmethod
    def from_result(cls, result: EventResult, timestamp: str) -> "EventMetadata":
        event = result.event
        best = event.best
        box = best.enclosing_box
        identification = result.identification
        return cls(
            timestamp=timestamp,
            event_id=result.id,
            camera=camera_id(event.source),
            validated=result.validation.validated,
            confidence=best.score,
            confidences=dict(best.confidence),
            detections=len(event.observations),
            start=event.start.isoformat(),
            end=event.end.isoformat(),
            duration=event.duration,
            crop=CropMetadata(x1=box.x1, y1=box.y1, x2=box.x2, y2=box.y2)
            if box
            else None,
            validation_error=result.validation.error,
            individuals=None
            if identification is None or identification.error is not None
            else [
                IndividualMetadata(
                    track=individual.track_id,
                    label=individual.label,
                    sighting=individual.sighting,
                    name=individual.name,
                    candidates=[
                        CandidateMetadata(name=candidate.name, score=candidate.score)
                        for candidate in individual.candidates
                    ],
                )
                for individual in identification.individuals
            ],
            individuals_error=identification.error if identification else None,
        )
