import json
from datetime import datetime
from pathlib import Path

import litellm
import numpy as np
import pytest
from litellm.types.utils import ModelResponse

from aidetector.adapters.media.event_media import EventMedia
from aidetector.adapters.vlm import VlmValidator, run_check
from aidetector.application.ports import ValidationUnavailable
from aidetector.configuration import DetectorConfig, VLMConfig
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
        (
            VLMConfig(
                key="test-key", model="test/model", prompt="Detect?", strategy="VIDEO"
            ),
        ),
        EventMedia(),
    )
    with pytest.raises(ValidationUnavailable, match="media encoding failed"):
        validator.validate(event)


def response_with(content):
    return ModelResponse(
        choices=[{"message": {"role": "assistant", "content": content}}]
    )


def response(detected):
    return response_with(json.dumps({"detected": detected}))


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
        return response(detected)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(
        key="test-key", model="model", prompt="Detect?", strategy="IMAGE"
    )
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
                key="test-key",
                model=("video-one", "video-two"),
                prompt="Detect?",
                strategy="VIDEO",
            ),
            VLMConfig(
                key="test-key", model="image", prompt="Detect?", strategy="IMAGE"
            ),
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
        key="test-key",
        model=("first", "second"),
        prompt="Detect?",
        strategy="IMAGE",
        timeout=7,
    )
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.REJECTED
    assert len(calls) == 1
    assert calls[0]["timeout"] == 7
    assert calls[0]["num_retries"] == 0
    assert calls[0]["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param(response("false"), id="text"),
        pytest.param(response(1), id="number"),
        pytest.param(response(None), id="null"),
        pytest.param(response_with("{}"), id="no decision"),
        pytest.param(
            response_with('{"detected": true, "unexpected": 1}'), id="extra field"
        ),
        pytest.param(response_with("bad JSON"), id="not JSON"),
        pytest.param(response_with(None), id="no content"),
        pytest.param(ModelResponse(choices=[]), id="no choices"),
    ],
)
def test_invalid_provider_answer_uses_next_model(event, monkeypatch, invalid):
    answers = iter([invalid, response(True)])
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        return next(answers)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig(
        key="test-key", model=("first", "second"), prompt="Detect?", strategy="IMAGE"
    )
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
    config = VLMConfig(
        key="test-key", model=("first", "second"), prompt="Detect?", strategy="IMAGE"
    )
    with pytest.raises(error_type, match="Unexpected SDK failure"):
        VlmValidator((config,), EventMedia()).validate(event)
    assert calls == ["first"]


def test_unavailable_provider_has_bounded_retries_and_safe_error(event, monkeypatch):
    calls, waits = [], []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        raise litellm.APIConnectionError(
            message="private-key", llm_provider="test", model="model"
        )

    monkeypatch.setattr(litellm, "completion", complete)
    monkeypatch.setattr("aidetector.adapters.vlm.sleep", waits.append)
    config = VLMConfig(
        key="test-key", model=("model",), prompt="Detect?", strategy="IMAGE", attempts=3
    )
    with pytest.raises(ValidationUnavailable) as raised:
        VlmValidator((config,), EventMedia()).validate(event)
    assert calls == ["model"] * 3
    assert waits == [1, 2]
    assert "private-key" not in str(raised.value)
    assert raised.value.failures == ("APIConnectionError",)


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
    config = VLMConfig(
        key="test-key", model=("first", "second"), prompt="Detect?", strategy="IMAGE"
    )
    answer = VlmValidator((config,), EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert calls == ["first", "second"]


@pytest.mark.parametrize(
    "failure", [litellm.RateLimitError, litellm.ServiceUnavailableError]
)
def test_connected_model_lists_fall_back_to_another_key(event, monkeypatch, failure):
    requests = []

    def complete(**kwargs):
        requests.append((kwargs["model"], kwargs["api_key"]))
        if kwargs["api_key"] == "primary-key":
            raise failure(
                message="Unavailable", llm_provider="test", model=kwargs["model"]
            )
        return response(True)

    monkeypatch.setattr(litellm, "completion", complete)
    detector = DetectorConfig.model_validate(
        {
            "detection": {"source": "video.mp4"},
            "vlm": [
                {"prompt": "Check?", "model": "disabled", "key": None},
                {
                    "prompt": "Check?",
                    "model": ["first", "second"],
                    "key": "primary-key",
                    "strategy": "IMAGE",
                    "attempts": 1,
                },
                {
                    "prompt": "Check?",
                    "model": ["backup"],
                    "key": "backup-key",
                    "strategy": "IMAGE",
                    "attempts": 1,
                },
            ],
        }
    )
    answer = VlmValidator(detector.active_vlm, EventMedia()).validate(event)
    assert answer.status is ValidationStatus.APPROVED
    assert requests == [
        ("first", "primary-key"),
        ("second", "primary-key"),
        ("backup", "backup-key"),
    ]


@pytest.mark.parametrize(
    "preset_name",
    [
        "cow-catcher",
        "calving-catcher",
        "calving-catcher.low-power",
        "calving-catcher-tailup",
    ],
)
def test_preset_question_and_video_reach_provider(preset_name, event, monkeypatch):
    preset_path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "detector"
        / f"{preset_name}.json"
    )
    settings = json.loads(preset_path.read_text())["vlm"]
    assert settings["key"] is None
    assert settings["strategy"] == "VIDEO"
    requests = []

    def complete(**kwargs):
        requests.append(kwargs)
        return response(True)

    monkeypatch.setattr(litellm, "completion", complete)
    config = VLMConfig.model_validate(
        {**settings, "key": "test-key", "model": "test-vision"}
    )
    assert (
        VlmValidator((config,), EventMedia()).validate(event).status
        is ValidationStatus.APPROVED
    )
    assert requests[0]["messages"][0]["content"][0] == {
        "type": "text",
        "text": settings["prompt"],
    }
    media = requests[0]["messages"][0]["content"][1]
    assert media["type"] == "file"
    assert media["file"]["file_data"].startswith("data:video/mp4;base64,")


@pytest.mark.parametrize("detected", [True, False])
@pytest.mark.parametrize("key", ["secret-token", ""])
def test_check_uses_real_validation_contract_and_synthetic_media(
    tmp_path, monkeypatch, capsys, detected, key
):
    requests = []

    def complete(**kwargs):
        requests.append(kwargs)
        print("SDK diagnostic with secret-token")
        return ModelResponse(
            choices=[{"message": {"content": json.dumps({"detected": detected})}}]
        )

    monkeypatch.setattr(litellm, "completion", complete)
    file = tmp_path / "check.json"
    file.write_text(
        json.dumps(
            {
                "prompt": "Private question",
                "model": "openai/vision",
                "key": key,
                "headers": {"X-Tenant": "private"},
                "strategy": "IMAGE",
                "attempts": 10,
                "timeout": 60,
            }
        )
    )
    assert run_check(file) == 0
    [request] = requests
    assert request["extra_headers"] == {"X-Tenant": "private"}
    assert request["api_key"] == ("not-needed" if key == "" else key)
    assert request["timeout"] == 20
    assert request["num_retries"] == 0
    content = request["messages"][0]["content"]
    assert content[0]["text"] != "Private question"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert capsys.readouterr().out.strip() == "AI connection check passed."


def test_check_reports_auth_failure_without_echoing_credentials(
    tmp_path, monkeypatch, capsys
):
    def denied(**kwargs):
        raise litellm.AuthenticationError(
            message="secret-token rejected", llm_provider="openai", model="vision"
        )

    monkeypatch.setattr(litellm, "completion", denied)
    file = tmp_path / "check.json"
    file.write_text(
        json.dumps(
            {
                "prompt": "Check?",
                "model": "openai/vision",
                "key": "secret-token",
                "strategy": "IMAGE",
            }
        )
    )
    assert run_check(file) == 1
    output = capsys.readouterr()
    assert "AuthenticationError" in output.out
    assert "secret-token" not in output.out + output.err


@pytest.mark.parametrize("settings", [{}, {"key": None}])
def test_check_without_key_does_not_call_provider(
    tmp_path, monkeypatch, capsys, settings
):
    def unexpected(**kwargs):
        pytest.fail("A disconnected verifier must not contact the provider")

    monkeypatch.setattr(litellm, "completion", unexpected)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key-must-not-enable-validation")
    file = tmp_path / "check.json"
    file.write_text(
        json.dumps({"model": "openai/vision", "prompt": "Check?", **settings})
    )
    assert run_check(file) == 2
    assert "connection" in capsys.readouterr().out


def test_connection_check_uses_the_next_model_when_quota_is_exhausted(
    tmp_path, monkeypatch, capsys
):
    requests = []

    def complete(**kwargs):
        requests.append(kwargs)
        if kwargs["model"] == "first":
            raise litellm.RateLimitError(
                message="Quota exhausted", llm_provider="test", model="first"
            )
        return ModelResponse(choices=[{"message": {"content": '{"detected": true}'}}])

    monkeypatch.setattr(litellm, "completion", complete)
    file = tmp_path / "check.json"
    file.write_text(
        json.dumps(
            {
                "prompt": "Check?",
                "model": ["first", "backup"],
                "key": "test-key",
                "strategy": "IMAGE",
            }
        )
    )
    assert run_check(file) == 0
    assert [request["model"] for request in requests] == ["first", "backup"]
    assert all(request["api_key"] == "test-key" for request in requests)
    assert all(request["timeout"] == 10 for request in requests)
    assert capsys.readouterr().out.strip() == "AI connection check passed."
