from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from aidetector.adapters.health import Healthcheck
from aidetector.application.ports import DeliveryError
from aidetector.configuration import HealthcheckConfig


def test_healthcheck_stops_without_waiting_for_the_next_interval(monkeypatch):
    pinged = Event()
    request = Mock(side_effect=lambda *args, **kwargs: pinged.set())
    monkeypatch.setattr("aidetector.adapters.health.send_request", request)
    health = Healthcheck(
        HealthcheckConfig(url="https://health.example.test", interval=600)
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(health.run)
        try:
            assert pinged.wait(2)
        finally:
            health.stop()
        assert task.result(timeout=2) is None
    assert request.call_count == 1
    assert request.call_args.kwargs["timeout"] == 5


def test_expected_request_failure_is_logged_without_stopping_detection(
    monkeypatch, caplog
):
    attempted = Event()

    def unavailable(*args, **kwargs):
        attempted.set()
        raise DeliveryError("HTTP status 503")

    monkeypatch.setattr("aidetector.adapters.health.send_request", unavailable)
    health = Healthcheck(HealthcheckConfig(url="https://health.example.test"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(health.run)
        try:
            assert attempted.wait(2)
        finally:
            health.stop()
        assert task.result(timeout=2) is None
    assert "HTTP status 503" in caplog.text


def test_unexpected_health_failure_reaches_the_runner(monkeypatch):
    monkeypatch.setattr(
        "aidetector.adapters.health.send_request",
        Mock(side_effect=TypeError("programming error")),
    )
    health = Healthcheck(HealthcheckConfig(url="https://health.example.test"))
    with pytest.raises(TypeError, match="programming error"):
        health.run()
