import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from aidetector.application.ports import (
    DeliveryError,
    EventExporter,
    EventValidator,
    ValidationUnavailable,
)
from aidetector.application.status import ReportStatus, StatusEvent, ignore_status
from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    IdentityMatch,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, ExportPolicy

logger = logging.getLogger(__name__)
NameIndividuals = Callable[[DetectionEvent], tuple[IdentityMatch, ...]]


def name_nobody(event: DetectionEvent) -> tuple[IdentityMatch, ...]:
    return ()


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
        report_status: ReportStatus = ignore_status,
        name_individuals: NameIndividuals = name_nobody,
    ):
        self.destinations = destinations
        self.cooldown = cooldown
        self.validator = validator
        self.report_status = report_status
        self.name_individuals = name_individuals

    def deliver(self, event: DetectionEvent) -> DeliveryReport:
        logger.info(
            "Event collected: %d frame(s) over %.2fs; best confidence: %s",
            len(event.observations),
            event.duration,
            dict(event.best.confidence),
        )
        if not self.cooldown.allows(event):
            logger.info("Event skipped: cooldown is still active")
            return DeliveryReport(None)

        # Before validation: what was seen around the event is kept only briefly.
        seen = self.name_individuals(event)
        validation = self._validate(event)
        logger.info("Event validation: %s", validation.status.value)
        result = EventResult(event, validation, uuid4().hex, seen)
        self.cooldown.record(result)
        delivered: list[str] = []
        failures: list[DeliveryFailure] = []
        first_unexpected: Exception | None = None
        for destination in self.destinations:
            if not destination.policy.accepts(event, validation):
                logger.info(
                    "Export to %s skipped by confidence or validation policy",
                    destination.name,
                )
                continue
            try:
                logger.info("Exporting event to %s", destination.name)
                destination.exporter.export(result)
                delivered.append(destination.name)
                self.report_status(
                    StatusEvent(
                        "delivery", event.source, destination_id=destination.name
                    )
                )
                logger.info("Event delivered to %s", destination.name)
            except DeliveryError as error:
                failures.append(DeliveryFailure(destination.name, str(error)))
                logger.error("Delivery to %s failed: %s", destination.name, error)
                self.report_status(
                    StatusEvent(
                        "delivery_failed",
                        event.source,
                        message="Delivery failed. Check the connection and see Logs for details.",
                        destination_id=destination.name,
                    )
                )
            except Exception as error:
                # Try independent destinations before the supervisor stops this worker.
                logger.exception("Unexpected delivery failure at %s", destination.name)
                if first_unexpected is None:
                    first_unexpected = error
        if first_unexpected is not None:
            raise first_unexpected
        return DeliveryReport(result, tuple(delivered), tuple(failures))

    def _validate(self, event: DetectionEvent) -> ValidationResult:
        if self.validator is None:
            return ValidationResult(ValidationStatus.UNVALIDATED)
        logger.info("Validating event")
        try:
            validation = self.validator.validate(event)
        except ValidationUnavailable as error:
            validation = ValidationResult(ValidationStatus.FAILED, str(error))
            logger.error("Event validation unavailable: %s", error)
        failed = validation.status == ValidationStatus.FAILED
        self.report_status(
            StatusEvent(
                "validation_failed" if failed else "validation",
                event.source,
                message="Validator unavailable. Check the connection in Validator and see Logs for details."
                if failed
                else None,
            )
        )
        return validation
