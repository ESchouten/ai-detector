import logging
from dataclasses import dataclass
from uuid import uuid4

from aidetector.application.ports import (
    DeliveryError,
    EventExporter,
    EventIdentifier,
    EventValidator,
    IdentificationUnavailable,
    ReportStatus,
    StatusEvent,
    ValidationUnavailable,
    ignore_status,
)
from aidetector.domain.models import (
    DetectionEvent,
    EventResult,
    Identification,
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
class DeliveryReport:
    result: EventResult | None
    failures: int = 0


class EventDelivery:
    """Validate, identify and deliver events in order through domain policies."""

    def __init__(
        self,
        destinations: tuple[Destination, ...],
        cooldown: Cooldown,
        validator: EventValidator | None = None,
        report_status: ReportStatus = ignore_status,
        identifier: EventIdentifier | None = None,
    ):
        self.destinations = destinations
        self.cooldown = cooldown
        self.validator = validator
        self.report_status = report_status
        self.identifier = identifier

    def deliver(self, event: DetectionEvent) -> DeliveryReport:
        logger.info(
            "Event collected: %d frame(s) over %.2fs; best confidence: %s",
            len(event.observations),
            event.duration,
            dict(event.best.confidence),
        )
        if not self.cooldown.allows(event):
            logger.info("Event skipped: not enough frames outside cooldown")
            return DeliveryReport(None)

        validation = self._validate(event)
        logger.info("Event validation: %s", validation.status.value)
        event_id = uuid4().hex
        result = EventResult(
            event, validation, event_id, self._identify(event, event_id, validation)
        )
        self.cooldown.record(result)
        failures = 0
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
                self.report_status(
                    StatusEvent(
                        "delivery", event.source, destination_id=destination.name
                    )
                )
                logger.info("Event delivered to %s", destination.name)
            except DeliveryError as error:
                failures += 1
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
        return DeliveryReport(result, failures)

    def _identify(
        self, event: DetectionEvent, event_id: str, validation: ValidationResult
    ) -> Identification | None:
        if self.identifier is None or validation.status is ValidationStatus.REJECTED:
            return None
        try:
            individuals = self.identifier.identify(event, event_id)
        except IdentificationUnavailable as error:
            logger.error("Recognising individuals failed: %s", error)
            return Identification(error=str(error))
        logger.info(
            "Individuals: %s",
            ", ".join(
                individual.name
                or "/".join(candidate.name for candidate in individual.candidates)
                or "unnamed"
                for individual in individuals
            )
            or "none tracked",
        )
        return Identification(individuals)

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
