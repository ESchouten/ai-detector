"""Check a saved connection with synthetic media through the normal VLM adapter."""

import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.vlm import VlmUnavailable, VlmValidator
from aidetector.configuration import VLMConfig
from aidetector.domain.models import DetectionEvent, Observation

_CHECK_FAILURES = {
    "AuthenticationError": "Check the API key and authentication headers.",
    "PermissionDeniedError": "This key cannot use the model. Check the project's permissions.",
    "NotFoundError": "The model or endpoint was not found. Check their names and URL.",
    "RateLimitError": "The provider's usage limit was reached. Check your quota or try later.",
    "Timeout": "The service did not answer in time. Check its address and availability.",
    "APIConnectionError": "Could not reach the service. Check its address and your connection.",
    "InvalidAnswer": "The model did not return the required JSON answer. Choose a model that supports structured answers.",
    "BadRequestError": "The service rejected the image or response format. Check that the model supports both.",
}


def run_check(path: Path) -> int:
    try:
        config = VLMConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        print("Check the AI model, endpoint and connection settings.")
        return 2
    if config.key is None:
        print("Configure a key to test the connection.")
        return 2
    # Never read cameras or saved recordings. The check uses the same media,
    # request and response validation as monitoring, with one attempt per model.
    # Share the request timeout budget so fallback checks remain quick.
    sample = np.zeros((64, 64, 3), dtype=np.uint8)
    sample[16:48, 16:48] = 255
    event = DetectionEvent(
        "connection-test", (Observation(datetime(2026, 1, 1), sample, {}),)
    )
    config = config.model_copy(
        update={
            "prompt": "Is there a white square? Return the detected boolean.",
            "attempts": 1,
            "timeout": min(config.timeout, 20 / len(config.model)),
        }
    )
    try:
        # Provider SDK diagnostics can echo credentials. Only the adapter's safe
        # failure classification crosses this CLI boundary.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            VlmValidator((config,), EventMedia()).validate(event)
    except VlmUnavailable as error:
        guidance = next(
            (
                _CHECK_FAILURES[code]
                for code in error.failures
                if code in _CHECK_FAILURES
            ),
            "Check the model, endpoint and authentication settings, then try again.",
        )
        print(f"{guidance} {error}")
        return 1
    print("AI connection check passed.")
    return 0
