import json

import litellm
import pytest
from litellm.types.utils import ModelResponse
from pydantic import ValidationError

from aidetector.adapters.vlm_check import run_check
from aidetector.configuration import Config, VLMConfig


def test_disabled_prompt_is_valid_but_enabling_without_model_is_not():
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "video.mp4"},
                    "vlm": {"enabled": False, "prompt": "Is the event visible?"},
                }
            ]
        }
    )
    assert config.detectors[0].active_vlm == ()
    assert config.detectors[0].vlm[0].prompt == "Is the event visible?"
    assert Config.model_validate_json(config.model_dump_json()) == config
    with pytest.raises(ValidationError, match="requires a model"):
        VLMConfig(prompt="Check?")
    with pytest.raises(ValidationError, match="requires a model"):
        VLMConfig(prompt="Check?", model=())


@pytest.mark.parametrize("detected", [True, False])
@pytest.mark.parametrize("key", ["secret-token", "", None])
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


def test_pause_preserves_verifier_settings_and_enabled_fallbacks():
    config = Config.model_validate(
        {
            "detectors": [
                {
                    "detection": {"source": "video.mp4"},
                    "vlm_enabled": False,
                    "vlm": [
                        {"model": "first", "prompt": "First?"},
                        {"model": "backup", "prompt": "Backup?"},
                        {"model": "disabled", "prompt": "Disabled?", "enabled": False},
                    ],
                }
            ]
        }
    )
    detector = config.detectors[0]
    assert detector.active_vlm == ()
    resumed = detector.model_copy(update={"vlm_enabled": True})
    assert [v.model for v in resumed.active_vlm] == [("first",), ("backup",)]
    assert resumed.vlm == detector.vlm
