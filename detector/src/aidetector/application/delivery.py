import logging
from dataclasses import dataclass

from aidetector.application.ports import (
    DeliveryError,
    EventExporter,
    EventValidator,
    ValidationUnavailable,
)
from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, ExportPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Destination:
    name: str
    exporter: EventExporter
    policy: ExportPolicy


@dataclass(frozen=True)
class DeliveryFailure:
    destination: str
    message: str


@dataclass(frozen=True)
class DeliveryReport:
    result: EventResult | None
    delivered: tuple[str, ...] = ()
    failures: tuple[DeliveryFailure, ...] = ()

    @property
    def skipped(self) -> bool:
        return self.result is None


class EventDelivery:
    """Validate and deliver events in order through domain policies."""

    def __init__(
        self,
        destinations: tuple[Destination, ...],
        cooldown: Cooldown,
        validator: EventValidator | None = None,
    ):
        self.destinations = destinations
        self.cooldown = cooldown
        self.validator = validator

    def deliver(self, event: DetectionEvent) -> DeliveryReport:
        if not self.cooldown.allows(event):
            return DeliveryReport(None)

        try:
            validation = (
                self.validator.validate(event)
                if self.validator is not None
                else ValidationResult(ValidationStatus.UNVALIDATED)
            )
        except ValidationUnavailable as error:
            validation = ValidationResult(ValidationStatus.FAILED, str(error))
            logger.error("Event validation unavailable: %s", error)

        result = EventResult(event, validation)
        self.cooldown.record(result)
        delivered: list[str] = []
        failures: list[DeliveryFailure] = []
        first_unexpected: Exception | None = None
        for destination in self.destinations:
            if not destination.policy.accepts(event, validation):
                continue
            try:
                destination.exporter.export(result)
                delivered.append(destination.name)
            except DeliveryError as error:
                failures.append(DeliveryFailure(destination.name, str(error)))
                logger.error("Delivery to %s failed: %s", destination.name, error)
            except Exception as error:
                # Try independent destinations before the supervisor stops this worker.
                logger.exception("Unexpected delivery failure at %s", destination.name)
                if first_unexpected is None:
                    first_unexpected = error
        if first_unexpected is not None:
            raise first_unexpected
        return DeliveryReport(result, tuple(delivered), tuple(failures))
