from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aidetector.domain.models import EventResult


class CropMetadata(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


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
    validated: bool | None
    confidence: float = Field(ge=0, le=1)
    confidences: dict[str, float]
    detections: int = Field(ge=1)
    start: str
    end: str
    duration: float = Field(ge=0)
    crop: CropMetadata | None = None
    validation_error: str | None = None
    # The web application adds this to a published metadata.json when someone reviews
    # the event, leaving `validated` as the validator's own result. The detector
    # describes it here for the shared schema and never writes it.
    review: ManualReview | None = Field(default=None, exclude=True)

    @classmethod
    def from_result(cls, result: EventResult, timestamp: str) -> "EventMetadata":
        event = result.event
        best = event.best
        box = best.enclosing_box
        return cls(
            timestamp=timestamp,
            event_id=result.id,
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
        )
