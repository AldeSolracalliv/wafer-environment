import sys
from types import SimpleNamespace

import pytest

from app.models import ModelError, ModelMessage, ModelRequest, ModelResponse, ModelUsage
from app.providers.openai_client import OpenAIModelClient


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def test_openai_adapter_translates_messages_and_response_without_sdk_types():
    responses = FakeResponses(response=SimpleNamespace(
        output_text="generated",
        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        model="provider-model-version",
    ))
    client = OpenAIModelClient(
        "selected-model",
        client=SimpleNamespace(responses=responses),
    )
    request = ModelRequest((
        ModelMessage("system", "system instruction"),
        ModelMessage("user", "user content"),
    ))

    result = client.generate(request)

    assert result == ModelResponse(
        "generated",
        ModelUsage(input_tokens=12, output_tokens=8),
        "provider-model-version",
    )
    assert responses.calls == [{
        "model": "selected-model",
        "input": [
            {"role": "system", "content": "system instruction"},
            {"role": "user", "content": "user content"},
        ],
        "max_output_tokens": 800,
        "store": False,
    }]


def test_openai_adapter_sanitizes_sdk_failures():
    client = OpenAIModelClient(
        "selected-model",
        client=SimpleNamespace(responses=FakeResponses(error=RuntimeError("secret token payload"))),
    )

    with pytest.raises(ModelError, match="OpenAI generation failed") as error:
        client.generate(ModelRequest((ModelMessage("user", "safe test"),)))

    assert "secret token payload" not in str(error.value)


def test_openai_adapter_requires_environment_credential_when_not_injected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ModelError, match="OPENAI_API_KEY"):
        OpenAIModelClient("selected-model")


def test_openai_sdk_is_created_with_env_credential_and_retries_disabled(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(responses=FakeResponses(response=SimpleNamespace(
            output_text="ok", usage=None, model="model",
        )))

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-credential")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fake_openai))

    client = OpenAIModelClient("selected-model")
    result = client.generate(ModelRequest((ModelMessage("user", "hello"),)))

    assert captured == {
        "api_key": "test-only-credential",
        "max_retries": 0,
        "timeout": 30.0,
    }
    assert result == ModelResponse("ok", model="model")


def test_openai_host_composition_requires_agent_selection_and_is_explicit(tmp_path, monkeypatch):
    from app.host import create_openai_host
    from app.tools.model_generate import MODEL_GENERATE_TOOL

    config = tmp_path / "config.toml"
    config.write_text(
        '[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = []\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be listed"):
        create_openai_host(config, model="selected-model")

    config.write_text(
        '[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["error_explainer"]\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("WAFER_OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="WAFER_OPENAI_MODEL"):
        create_openai_host(config)

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-credential")
    monkeypatch.setenv("WAFER_OPENAI_MODEL", "selected-model")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=lambda **_: SimpleNamespace(responses=FakeResponses()),
    ))

    host = create_openai_host(config)

    assert host.agent_registry.get_agent("error_explainer") is not None
    assert host.tool_registry.get_tool(MODEL_GENERATE_TOOL) is not None
    assert host.permission_manager.list_grants("error_explainer") == []
    host.close()
