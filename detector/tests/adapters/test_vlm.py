import json
from datetime import datetime

import litellm
import numpy as np
import pytest
from litellm.types.utils import ModelResponse

from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.vlm import VlmValidator
from aidetector.application.ports import ValidationUnavailable
from aidetector.configuration import VLMConfig
from aidetector.domain.models import DetectionEvent, Observation, ValidationStatus


@pytest.fixture
def event():
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((24, 32, 3), dtype=np.uint8), {"cow": 0.9}
    )
    return DetectionEvent("camera", (observation,))


def test_ffmpeg_discovery_failure_is_unavailable_validation(event, monkeypatch):
    def unavailable():
        raise RuntimeError("No ffmpeg exe could be found")

    monkeypatch.setattr("aidetector.adapters.media.video.get_ffmpeg_exe", unavailable)
    validator = VlmValidator(
        (VLMConfig(model="test/model", prompt="Detect?", strategy="VIDEO"),),
        EventMedia(),
    )
    with pytest.raises(ValidationUnavailable, match="media encoding failed"):
        validator.validate(event)


def response(detected):
    return ModelResponse(
        choices=[
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"detected": detected}),
                }
            }
        ]
    )


@pytest.mark.parametrize(
    "detected, status",
    [(True, ValidationStatus.APPROVED), (False, ValidationStatus.REJECTED)],
)
def test_verifier_requests_and_accepts_only_the_boolean_decision(
    event, monkeypatch, detected, status
):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return ModelResponse(
            choices=[{"message": {"content": json.dumps({"detected": detected})}}]
        )

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model="model", prompt="Detect?", strategy="IMAGE")
    assert VlmValidator((config,), EventMedia()).validate(event).status is status
    [request] = calls
    response_format = request["response_format"]
    schema = response_format.model_json_schema()
    assert schema["required"] == ["detected"]
    assert set(schema["properties"]) == {"detected"}
    assert schema["properties"]["detected"]["type"] == "boolean"
    assert schema["additionalProperties"] is False


def test_media_failure_uses_the_next_verifier_configuration(event, monkeypatch):
    calls = []

    def unavailable():
        raise RuntimeError("FFmpeg is unavailable")

    def complete(**kwargs):
        calls.append(kwargs)
        return response(True)

    monkeypatch.setattr("aidetector.adapters.media.video.get_ffmpeg_exe", unavailable)
    monkeypatch.setattr(litellm, "completion", complete)
    validator = VlmValidator(
        (
            VLMConfig(
                model=("video-one", "video-two"), prompt="Detect?", strategy="VIDEO"
            ),
            VLMConfig(model="image", prompt="Detect?", strategy="IMAGE"),
        ),
        EventMedia(),
    )
    assert validator.validate(event).status is ValidationStatus.APPROVED
    assert [call["model"] for call in calls] == ["image"]
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_negative_validation_is_final_and_does_not_trigger_fallback(event, monkeypatch):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return response(False)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(
        model=("first", "second"), prompt="Detect?", strategy="IMAGE", timeout=7
    )
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.REJECTED
    assert len(calls) == 1
    assert calls[0]["timeout"] == 7
    assert calls[0]["num_retries"] == 0
    assert calls[0]["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


@pytest.mark.parametrize("detected", ["false", 1, None])
def test_non_boolean_provider_answer_uses_next_model(event, monkeypatch, detected):
    answers = iter([response(detected), response(True)])
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        return next(answers)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model=("first", "second"), prompt="Detect?", strategy="IMAGE")
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert calls == ["first", "second"]


@pytest.mark.parametrize(
    "content", ["{}", '{"detected": true, "unexpected": 1}', "bad JSON"]
)
def test_invalid_answer_shape_uses_next_model(event, monkeypatch, content):
    answers = iter(
        [ModelResponse(choices=[{"message": {"content": content}}]), response(True)]
    )
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        return next(answers)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model=("first", "second"), prompt="Detect?", strategy="IMAGE")
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert calls == ["first", "second"]


@pytest.mark.parametrize("error_type", [IndexError, ValueError])
def test_verifier_programming_errors_do_not_trigger_provider_fallback(
    event, monkeypatch, error_type
):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        raise error_type("Unexpected SDK failure")

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model=("first", "second"), prompt="Detect?", strategy="IMAGE")
    with pytest.raises(error_type, match="Unexpected SDK failure"):
        VlmValidator((config,), EventMedia()).validate(event)
    assert calls == ["first"]


@pytest.mark.parametrize("choices", [[], [{"message": {"content": None}}]])
def test_missing_provider_answer_uses_next_model(event, monkeypatch, choices):
    invalid = ModelResponse(choices=choices)
    answers = iter([invalid, response(True)])
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        return next(answers)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model=("first", "second"), prompt="Detect?", strategy="IMAGE")
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert calls == ["first", "second"]


def test_unavailable_provider_has_bounded_retries_and_safe_error(event, monkeypatch):
    calls, waits = [], []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        raise litellm.APIConnectionError(
            message="private-key", llm_provider="test", model="model"
        )

    monkeypatch.setattr(litellm, "completion", complete)
    monkeypatch.setattr("aidetector.adapters.vlm.sleep", waits.append)
    config = VLMConfig(model=("model",), prompt="Detect?", strategy="IMAGE", attempts=3)
    with pytest.raises(ValidationUnavailable) as raised:
        VlmValidator((config,), EventMedia()).validate(event)
    assert calls == ["model"] * 3
    assert waits == [1, 2]
    assert "private-key" not in str(raised.value)


def test_authentication_failure_uses_provider_fallback_without_retry(
    event, monkeypatch
):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "first":
            raise litellm.AuthenticationError(
                message="secret", llm_provider="test", model="first"
            )
        return response(True)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(model=("first", "second"), prompt="Detect?", strategy="IMAGE")
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert calls == ["first", "second"]
