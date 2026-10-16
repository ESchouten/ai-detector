import base64
import io
import logging
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import cast

import litellm
import numpy as np
from litellm.types.utils import Choices, ModelResponse
from openai import APIError as ProviderError
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.application.ports import ValidationUnavailable
from aidetector.configuration import VLMConfig
from aidetector.domain.models import (
    DetectionEvent,
    Observation,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: StrictBool


class InvalidAnswer(ValueError):
    """A provider response that does not satisfy the structured answer contract."""


class VlmUnavailable(ValidationUnavailable):
    """Safe failure codes for diagnostics and connection-check guidance."""

    def __init__(self, failures: list[str]):
        self.failures = tuple(dict.fromkeys(failures))
        super().__init__(
            f"No configured verifier returned a valid answer ({', '.join(self.failures)})"
        )


def _request_answer(config: VLMConfig, model: str, content: list[dict]) -> _Answer:
    # LiteLLM's return union includes streaming responses;
    # this call explicitly selects the non-streaming API.
    response = cast(
        ModelResponse,
        litellm.completion(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format=_Answer,
            # An explicit empty key selects an unauthenticated local service.
            # LiteLLM otherwise falls back to environment keys, and its OpenAI
            # client requires a nonempty value even for a server without auth.
            api_key="not-needed" if config.key == "" else config.key,
            base_url=config.url,
            extra_headers=config.headers or None,
            timeout=config.timeout,
            num_retries=0,
            stream=False,
        ),
    )
    if not response.choices:
        raise InvalidAnswer("Provider returned no answer choices")
    choice = response.choices[0]
    if not isinstance(choice, Choices) or choice.message.content is None:
        raise InvalidAnswer("Provider returned no answer text")
    try:
        return _Answer.model_validate_json(choice.message.content)
    except ValidationError as error:
        raise InvalidAnswer("Provider returned an invalid structured answer") from error


class VlmValidator:
    def __init__(self, configs: tuple[VLMConfig, ...], media: EventMedia):
        self.configs = configs
        self.media = media

    def validate(self, event: DetectionEvent) -> ValidationResult:
        failures: list[str] = []
        for config_index, config in enumerate(self.configs):
            try:
                content = self._content(event, config)
            except MediaError as error:
                failures.append("media encoding failed")
                logger.warning(
                    "Verifier %d media encoding failed: %s", config_index + 1, error
                )
                continue
            for model_index, model in enumerate(config.model):
                for attempt in range(config.attempts):
                    try:
                        answer = _request_answer(config, model, content)
                        return ValidationResult(
                            ValidationStatus.APPROVED
                            if answer.detected
                            else ValidationStatus.REJECTED
                        )
                    except (
                        litellm.ServiceUnavailableError,
                        litellm.RateLimitError,
                        litellm.Timeout,
                        litellm.APIConnectionError,
                        litellm.InternalServerError,
                    ) as error:
                        failures.append(type(error).__name__)
                        logger.warning(
                            "Verifier %d model %d failed (%s), attempt %d/%d",
                            config_index + 1,
                            model_index + 1,
                            type(error).__name__,
                            attempt + 1,
                            config.attempts,
                        )
                        if attempt + 1 < config.attempts:
                            sleep(min(2**attempt, 4))
                    except (ProviderError, InvalidAnswer) as error:
                        failures.append(type(error).__name__)
                        break
        raise VlmUnavailable(failures)

    def _content(self, event: DetectionEvent, config: VLMConfig) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": config.prompt}]
        if config.strategy == "VIDEO":
            video = self.media.video(
                event, width=1280, crf=28, padding=config.crop_padding, plot=False
            )
            data_url = "data:video/mp4;base64," + base64.b64encode(video).decode(
                "ascii"
            )
            content.append({"type": "file", "file": {"file_data": data_url}})
        else:
            image = self.media.image(
                event, "crop", config.crop_padding, plot_crop=False
            )
            if image is None:
                image = self.media.image(event, "original")
            data_url = "data:image/jpeg;base64," + base64.b64encode(image).decode(
                "ascii"
            )
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        return content


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
    """Check a saved connection with synthetic media through the normal adapter."""
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
