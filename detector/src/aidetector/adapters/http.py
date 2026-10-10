from collections.abc import Mapping

import requests

from aidetector.application.ports import DeliveryError

Files = Mapping[str, tuple[str, bytes, str]]


def send_request(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    data: str | Mapping[str, object] | None = None,
    files: Files | None = None,
    json_body: Mapping[str, object] | None = None,
) -> requests.Response:
    try:
        response = requests.request(
            method,
            url,
            timeout=timeout,
            headers=headers,
            data=data,
            files=files,
            json=json_body,
        )
    except requests.RequestException as error:
        # Request exceptions can contain credentials embedded in URLs or headers.
        raise DeliveryError(f"HTTP request failed ({type(error).__name__})") from error
    if response.status_code >= 400:
        raise DeliveryError(f"HTTP request returned status {response.status_code}")
    return response
