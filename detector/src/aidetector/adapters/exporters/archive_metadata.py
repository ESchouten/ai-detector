from pydantic import BaseModel, ConfigDict, Field

from aidetector.domain.models import EventResult


class CropMetadata(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class EventMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    validated: bool | None
    confidence: float = Field(ge=0, le=1)
    confidences: dict[str, float]
    detections: int = Field(ge=1)
    start: str
    end: str
    duration: float = Field(ge=0)
    crop: CropMetadata | None = None
    validation_error: str | None = None

    @classmethod
    def from_result(cls, result: EventResult, timestamp: str) -> "EventMetadata":
        event = result.event
        best = event.best
        box = best.enclosing_box
        return cls(
            timestamp=timestamp,
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
