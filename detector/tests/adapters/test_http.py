from unittest.mock import Mock

import pytest
import requests

from aidetector.adapters.http import send_request
from aidetector.application.ports import DeliveryError


@pytest.mark.parametrize("status", [200, 204])
def test_successful_request_returns_the_response_for_provider_validation(
    monkeypatch, status
):
    response = requests.Response()
    response.status_code = status
    monkeypatch.setattr(requests, "request", Mock(return_value=response))

    assert send_request("POST", "https://example.test", timeout=3) is response


@pytest.mark.parametrize("status", [403, 503])
def test_http_failure_reports_status_without_the_url_or_response_body(
    monkeypatch, status
):
    response = requests.Response()
    response.status_code = status
    response.url = "https://example.test/private-token"
    response._content = b"Request with secret-header was rejected"
    monkeypatch.setattr(requests, "request", Mock(return_value=response))

    with pytest.raises(DeliveryError) as failure:
        send_request(
            "POST",
            response.url,
            timeout=3,
            headers={"Authorization": "secret-header"},
        )

    assert str(failure.value) == f"HTTP request returned status {status}"


@pytest.mark.parametrize("error_type", [requests.ConnectionError, requests.Timeout])
def test_request_exception_reports_its_kind_without_credential_details(
    monkeypatch, error_type
):
    request = Mock(
        side_effect=error_type("https://example.test/private-token secret-header")
    )
    monkeypatch.setattr(requests, "request", request)

    with pytest.raises(DeliveryError) as failure:
        send_request(
            "POST",
            "https://example.test/private-token",
            timeout=3,
            headers={"Authorization": "secret-header"},
        )

    assert str(failure.value) == f"HTTP request failed ({error_type.__name__})"
    assert request.call_count == 1
