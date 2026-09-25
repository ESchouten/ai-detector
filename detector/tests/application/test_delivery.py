from datetime import datetime, timedelta

import numpy as np
import pytest

from aidetector.application.delivery import Destination, EventDelivery
from aidetector.application.ports import DeliveryError, ValidationUnavailable
from aidetector.domain.models import (
    DetectionEvent,
    Observation,
    ValidationResult,
    ValidationStatus,
)
from aidetector.domain.policy import Cooldown, ExportPolicy


def event(second=0):
    observation = Observation(
        datetime(2026, 1, 1) + timedelta(seconds=second),
        np.zeros((8, 8, 3), dtype=np.uint8),
        {"cow": 0.9},
    )
    return DetectionEvent("camera", (observation,))


class RecordingExporter:
    def __init__(self, error=None):
        self.results = []
        self.error = error

    def export(self, result):
        self.results.append(result)
        if self.error:
            raise self.error


class Validator:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def validate(self, event):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return ValidationResult(self.result)


def test_optional_validation_exports_unvalidated_event(caplog):
    caplog.set_level("INFO")
    exporter = RecordingExporter()
    delivery = EventDelivery(
        (Destination("disk", exporter, ExportPolicy()),), Cooldown()
    )
    report = delivery.deliver(event())
    assert report.delivered == ("disk",)
    assert report.failures == ()
    assert exporter.results[0].validation.status is ValidationStatus.UNVALIDATED
    assert "Event collected: 1 frame(s) over 0.00s" in caplog.text
    assert "Event validation: unvalidated" in caplog.text
    assert "Event delivered to disk" in caplog.text


@pytest.mark.parametrize(
    "threshold,rejected,expected",
    [
        (0.95, True, ()),
        (0.5, False, ()),
        (0.5, True, ("disk",)),
        ({"horse": 0.5}, True, ()),
        ({"cow": 0.9}, True, ("disk",)),
    ],
)
def test_export_filters_combine_confidence_and_rejection_policy(
    threshold, rejected, expected
):
    exporter = RecordingExporter()
    delivery = EventDelivery(
        (Destination("disk", exporter, ExportPolicy(threshold, rejected)),),
        Cooldown(),
        Validator(ValidationStatus.REJECTED),
    )
    report = delivery.deliver(event())
    assert report.delivered == expected
    assert len(exporter.results) == len(expected)


def test_cooldown_prevents_repeated_validation_calls(caplog):
    caplog.set_level("INFO")
    validator = Validator(ValidationStatus.APPROVED)
    delivery = EventDelivery((), Cooldown(10), validator)
    assert not delivery.deliver(event(0)).skipped
    assert delivery.deliver(event(9)).skipped
    assert not delivery.deliver(event(10)).skipped
    assert validator.calls == 2
    assert caplog.messages.count("Event skipped: cooldown is still active") == 1
    assert caplog.messages.count("Event validation: approved") == 2


@pytest.mark.parametrize(
    "outcome", [ValidationStatus.REJECTED, ValidationUnavailable("offline")]
)
def test_rejection_or_unavailable_validation_does_not_consume_cooldown(outcome):
    validator = Validator(outcome)
    delivery = EventDelivery((), Cooldown(10), validator)
    delivery.deliver(event(0))
    delivery.deliver(event(1))
    assert validator.calls == 2


@pytest.mark.parametrize("verified", [False, True])
def test_delivery_failure_does_not_undo_acceptance_cooldown(verified):
    exporter = RecordingExporter(DeliveryError("HTTP status 503"))
    validator = Validator(ValidationStatus.APPROVED) if verified else None
    delivery = EventDelivery(
        (Destination("webhook", exporter, ExportPolicy()),), Cooldown(10), validator
    )

    first = delivery.deliver(event(0))
    repeated = delivery.deliver(event(1))

    assert first.failures[0].destination == "webhook"
    assert repeated.skipped
    assert len(exporter.results) == 1


def test_failed_validation_is_archived_but_does_not_notify():
    archive, notification = RecordingExporter(), RecordingExporter()
    delivery = EventDelivery(
        (
            Destination("disk", archive, ExportPolicy(archive_failed_validation=True)),
            Destination("webhook", notification, ExportPolicy(export_rejected=True)),
        ),
        Cooldown(),
        Validator(ValidationUnavailable("All configured models are unavailable")),
    )
    report = delivery.deliver(event())
    assert report.delivered == ("disk",)
    assert notification.results == []
    assert archive.results[0].validation.status is ValidationStatus.FAILED
    assert (
        archive.results[0].validation.error == "All configured models are unavailable"
    )


def test_failed_destination_does_not_prevent_independent_destination(caplog):
    caplog.set_level("INFO")
    broken = RecordingExporter(DeliveryError("HTTP status 503"))
    working = RecordingExporter()
    delivery = EventDelivery(
        (
            Destination("webhook", broken, ExportPolicy()),
            Destination("disk", working, ExportPolicy()),
        ),
        Cooldown(),
    )
    report = delivery.deliver(event())
    assert report.delivered == ("disk",)
    assert [(failure.destination, failure.message) for failure in report.failures] == [
        ("webhook", "HTTP status 503")
    ]
    assert "Delivery to webhook failed: HTTP status 503" in caplog.text
    assert "Event delivered to webhook" not in caplog.text
    assert "Event delivered to disk" in caplog.text


def test_programming_error_surfaces_after_independent_destinations_are_attempted():
    working = RecordingExporter()
    delivery = EventDelivery(
        (
            Destination("broken", RecordingExporter(TypeError("bug")), ExportPolicy()),
            Destination("disk", working, ExportPolicy()),
        ),
        Cooldown(),
    )
    with pytest.raises(TypeError, match="bug"):
        delivery.deliver(event())
    assert len(working.results) == 1


def test_all_unexpected_destination_failures_remain_observable(caplog):
    working = RecordingExporter()
    first_error = TypeError("first bug")
    delivery = EventDelivery(
        (
            Destination("first", RecordingExporter(first_error), ExportPolicy()),
            Destination(
                "second", RecordingExporter(RuntimeError("second bug")), ExportPolicy()
            ),
            Destination("working", working, ExportPolicy()),
        ),
        Cooldown(),
    )
    with pytest.raises(TypeError, match="first bug") as caught:
        delivery.deliver(event())
    assert caught.value is first_error
    assert len(working.results) == 1
    assert "Unexpected delivery failure at first" in caplog.text
    assert "Unexpected delivery failure at second" in caplog.text
    assert "second bug" in caplog.text
