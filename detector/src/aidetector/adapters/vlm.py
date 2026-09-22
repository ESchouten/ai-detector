import base64
import logging
from time import sleep
from typing import cast

import litellm
from litellm.types.utils import Choices, ModelResponse
from openai import APIError as ProviderError
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from aidetector.adapters.media import MediaError
from aidetector.adapters.media.event_media import EventMedia
from aidetector.application.ports import ValidationUnavailable
from aidetector.configuration import VLMConfig
from aidetector.domain.models import DetectionEvent, ValidationResult, ValidationStatus

logger = logging.getLogger(__name__)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: StrictBool


class InvalidAnswer(ValueError):
    """A provider response that does not satisfy the structured answer contract."""


def _request_answer(config: VLMConfig, model: str, content: list[dict]) -> _Answer:
    # LiteLLM's return union includes streaming responses;
    # this call explicitly selects the non-streaming API.
    response = cast(
        ModelResponse,
        litellm.completion(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format=_Answer,
            api_key=config.key,
            base_url=config.url,
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
        reason = ", ".join(dict.fromkeys(failures))
        raise ValidationUnavailable(
            f"No configured verifier returned a valid answer ({reason})"
        )

    def _content(self, event: DetectionEvent, config: VLMConfig) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": config.prompt}]
        if config.strategy == "VIDEO":
            video = self.media.video(event, padding=config.crop_padding, plot=False)
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
