from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aidetector.adapters.operational_status import source_key
from aidetector.domain.models import EventResult


class CropMetadata(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class IdentityMetadata(BaseModel):
    """Matched individual visible in the event's best observation."""

    id: str
    name: str | None = None
    similarity: float | None = Field(default=None, ge=-1, le=1)


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
    identities: list[IdentityMetadata] = Field(default_factory=list)
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
            camera=source_key(event.source)[:12],
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
            identities=[
                IdentityMetadata(
                    id=box.identity.identity_id,
                    name=box.identity.name,
                    similarity=box.identity.similarity,
                )
                for box in best.boxes
                if box.identity is not None and box.identity.identity_id is not None
            ],
        )
