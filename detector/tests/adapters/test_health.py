from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from aidetector.adapters.health import Healthcheck
from aidetector.application.ports import DeliveryError, SourceBatch, SourceError
from aidetector.bootstrap import run_application
from aidetector.configuration import Config, HealthcheckConfig


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


def test_health_failure_stops_all_sources_even_if_one_cannot_close(
    monkeypatch, tmp_path
):
    class WaitingSource:
        def __init__(self, name, fail_close=False):
            self.sources = (name,)
            self.started = Event()
            self.stopped = Event()
            self.fail_close = fail_close

        def batches(self):
            self.started.set()
            assert self.stopped.wait(5), "Source never received the stop request"
            yield SourceBatch({})

        def close(self):
            if self.fail_close:
                raise SourceError("Capture did not close")
            self.stopped.set()

    first = WaitingSource("0", fail_close=True)
    second = WaitingSource("1")
    sources = iter((first, second))
    monkeypatch.setattr(
        "aidetector.bootstrap.build_source", lambda *args: next(sources)
    )

    def fail_health(*args, **kwargs):
        assert first.started.wait(2) and second.started.wait(2)
        raise TypeError("Health worker failed")

    monkeypatch.setattr("aidetector.adapters.health.send_request", fail_health)
    config = Config.model_validate(
        {
            "detectors": [
                {"detection": {"source": "0"}},
                {"detection": {"source": "1"}},
            ],
            "health": {"url": "https://health.example.test"},
        }
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run_application, config, tmp_path, tmp_path)
        try:
            assert second.stopped.wait(2), (
                "A failed close prevented later stop requests"
            )
        finally:
            first.stopped.set()
            second.stopped.set()
            with pytest.raises(SourceError, match="Capture did not close"):
                task.result(timeout=5)
