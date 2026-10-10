import json

import litellm
import pytest
from litellm.types.utils import ModelResponse

from aidetector.adapters.vlm_check import run_check


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
