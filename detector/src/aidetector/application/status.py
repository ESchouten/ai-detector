"""Operational observations reported by I/O boundaries, separate from event rules."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StatusEvent:
    kind: Literal[
        "preparing",
        "preparation_failed",
        "ready",
        "models_ready",
        "frame",
        "inference",
        "processed",
        "recording",
        "offline",
        "recording_failed",
        "notice",
        "backend",
        "validation",
        "validation_failed",
        "delivery",
        "delivery_failed",
        "waiting_delivery",
        "processing_resumed",
        "identity_collecting",
        "identity_preparing",
        "identity_ready",
        "identity_failed",
    ]
    source: str | None = None
    message: str | None = None
    rule_id: str | None = None
    destination_id: str | None = None


ReportStatus = Callable[[StatusEvent], None]


def ignore_status(event: StatusEvent) -> None:
    """Ordinary CLI callers need no machine-readable status channel."""
