import json

import pytest

from app.agents.runtime import AgentRequest, AgentResultStatus
from app.core.wafer import Wafer
from app.host import create_host
from app.models import ModelError, ModelMessage, ModelRequest, ModelResponse, ModelUsage
from app.security.permissions import Permission
from app.tools.model_generate import MODEL_GENERATE_TOOL
from fake_model_client import FakeModelClient


VALID_EXPLANATION = json.dumps({
    "summary": "The application could not find the requested module.",
    "likely_causes": ["The package may not be installed in this environment."],
    "suggested_checks": ["Confirm the active Python environment and installed packages."],
})


def make_config(tmp_path, enabled_agents=("error_explainer",)):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config.toml"
    selected = ", ".join(json.dumps(agent_id) for agent_id in enabled_agents)
    config.write_text(
        f'[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = [{selected}]\n',
        encoding="utf-8",
    )
    return config


def make_host(tmp_path, client):
    host = create_host(make_config(tmp_path), model_client=client)
    host.permission_manager.grant("error_explainer", Permission.EXECUTE, MODEL_GENERATE_TOOL)
    return host


def test_model_contract_and_fake_client_capture_success_and_failure():
    request = ModelRequest((ModelMessage("user", "hello"),))
    response = ModelResponse("world", ModelUsage(1, 2), "test-model")
    client = FakeModelClient(response=response)

    assert client.generate(request) == response
    assert client.requests == [request]
    assert client.call_count == 1

    failure = ModelError("model generation failed")
    failing_client = FakeModelClient(error=failure)
    with pytest.raises(ModelError, match="model generation failed"):
        failing_client.generate(request)
    assert failing_client.requests == [request]
    assert failing_client.call_count == 1


def test_model_generate_tool_calls_client_and_returns_neutral_response(tmp_path):
    client = FakeModelClient(response=ModelResponse("generated text", ModelUsage(3, 4), "fake"))
    host = make_host(tmp_path, client)

    output = host.tool_registry.execute_tool(
        MODEL_GENERATE_TOOL,
        {"messages": [{"role": "user", "content": "prompt text"}]},
        requester="error_explainer",
    )

    assert output == {
        "text": "generated text",
        "model": "fake",
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }
    assert client.requests == [ModelRequest((ModelMessage("user", "prompt text"),))]
    assert client.call_count == 1
    host.close()


@pytest.mark.parametrize("parameters", [
    {},
    {"messages": []},
    {"messages": [{"role": "system", "content": "ok", "extra": "no"}]},
    {"messages": [{"role": "provider_specific", "content": "no"}]},
])
def test_model_generate_rejects_malformed_tool_input(tmp_path, parameters):
    client = FakeModelClient(response=ModelResponse("unused"))
    host = make_host(tmp_path, client)

    with pytest.raises(ValueError):
        host.tool_registry.execute_tool(MODEL_GENERATE_TOOL, parameters, requester="error_explainer")

    assert client.call_count == 0
    host.close()


def test_model_tool_denial_is_audited_and_does_not_call_client(tmp_path):
    client = FakeModelClient(response=ModelResponse("unused"))
    host = create_host(make_config(tmp_path), model_client=client)
    prompt_secret = "private-prompt-sentinel"

    with pytest.raises(PermissionError, match="not permitted"):
        host.tool_registry.execute_tool(
            MODEL_GENERATE_TOOL,
            {"messages": [{"role": "user", "content": prompt_secret}]},
            requester="error_explainer",
        )

    decision = host.permission_manager.recent_decisions(1)[0]
    assert decision.agent_id == "error_explainer"
    assert decision.tool_name == MODEL_GENERATE_TOOL
    assert decision.permission is Permission.EXECUTE
    assert not decision.allowed
    assert prompt_secret not in repr(decision)
    assert client.call_count == 0
    host.close()


def test_error_explainer_sends_only_allowlisted_input_and_returns_structured_output(tmp_path):
    client = FakeModelClient(response=ModelResponse(VALID_EXPLANATION))
    host = make_host(tmp_path, client)
    request = AgentRequest(
        "explain-1",
        "wafer.explain_error",
        context={
            "error_text": "ModuleNotFoundError: No module named 'example'",
            "operator_context": "Running the test suite",
        },
        configuration={"private_configuration": "do-not-send"},
        metadata={"private_metadata": "do-not-send"},
    )

    result = host.execute_agent("error_explainer", request)

    sent_user_content = json.loads(client.requests[0].messages[1].content)
    assert sent_user_content == {
        "error_text": "ModuleNotFoundError: No module named 'example'",
        "operator_context": "Running the test suite",
    }
    captured_messages = [
        {"role": message.role, "content": message.content}
        for message in client.requests[0].messages
    ]
    assert "do-not-send" not in json.dumps(captured_messages)
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output == json.loads(VALID_EXPLANATION)
    assert result.output == {
        "summary": "The application could not find the requested module.",
        "likely_causes": ["The package may not be installed in this environment."],
        "suggested_checks": ["Confirm the active Python environment and installed packages."],
    }
    assert client.call_count == 1
    decisions = host.permission_manager.recent_decisions(5)
    assert len(decisions) == 1
    assert decisions[0].tool_name == MODEL_GENERATE_TOOL and decisions[0].allowed
    host.close()


def test_error_explainer_accepts_omitted_optional_operator_context(tmp_path):
    client = FakeModelClient(response=ModelResponse(VALID_EXPLANATION))
    host = make_host(tmp_path, client)

    result = host.execute_agent(
        "error_explainer",
        AgentRequest("explain-optional", "wafer.explain_error", context={"error_text": "ValueError"}),
    )

    assert result.status is AgentResultStatus.COMPLETED
    assert json.loads(client.requests[0].messages[1].content) == {
        "error_text": "ValueError",
        "operator_context": "",
    }
    assert client.call_count == 1
    host.close()


@pytest.mark.parametrize("model_text", [
    "not json",
    '{"summary":"Only a summary"}',
    '{"summary":"ok","likely_causes":[],"suggested_checks":["check"]}',
])
def test_malformed_or_incomplete_model_output_is_a_structured_error(tmp_path, model_text):
    client = FakeModelClient(response=ModelResponse(model_text))
    host = make_host(tmp_path, client)

    result = host.execute_agent(
        "error_explainer",
        AgentRequest("explain-malformed", "wafer.explain_error", context={"error_text": "ValueError"}),
    )

    assert result.status is AgentResultStatus.ERROR
    assert result.output is None
    assert result.error
    assert client.call_count == 1
    host.close()


def test_model_error_becomes_sanitized_structured_runtime_error_without_retry(tmp_path):
    client = FakeModelClient(error=ModelError("provider failure credential=do-not-expose"))
    host = make_host(tmp_path, client)

    result = host.execute_agent(
        "error_explainer",
        AgentRequest("explain-failure", "wafer.explain_error", context={"error_text": "private input"}),
    )

    assert result.status is AgentResultStatus.ERROR
    assert result.error == "Model generation failed."
    assert "private input" not in result.error
    assert "do-not-expose" not in result.error
    assert client.call_count == 1
    assert [decision.tool_name for decision in host.permission_manager.recent_decisions(5)] == [MODEL_GENERATE_TOOL]
    host.close()


@pytest.mark.parametrize("context", [
    {},
    {"error_text": "   "},
    {"error_text": "error", "unexpected": "do not send"},
    {"error_text": "error", "operator_context": 3},
    {"error_text": "x" * 8_001},
])
def test_error_explainer_rejects_invalid_or_unbounded_input_before_model_call(tmp_path, context):
    client = FakeModelClient(response=ModelResponse(VALID_EXPLANATION))
    host = make_host(tmp_path, client)

    result = host.execute_agent(
        "error_explainer",
        AgentRequest("explain-invalid", "wafer.explain_error", context=context),
    )

    assert result.status is AgentResultStatus.ERROR
    assert client.call_count == 0
    assert host.permission_manager.recent_decisions(1) == []
    host.close()


def test_model_configuration_is_required_and_not_automatically_installed(tmp_path):
    config = make_config(tmp_path, enabled_agents=())
    host = create_host(config)
    assert host.agent_registry.get_agent("error_explainer") is None
    assert host.tool_registry.get_tool(MODEL_GENERATE_TOOL) is None
    host.close()

    with pytest.raises(ValueError, match="requires an explicitly configured ModelClient"):
        create_host(make_config(tmp_path / "selected"), model_client=None)

    wafer = Wafer(make_config(tmp_path / "plain", enabled_agents=()))
    assert wafer.agent_registry.list_agents() == []
    assert wafer.tool_registry.get_tool(MODEL_GENERATE_TOOL) is None
    wafer.close()


def test_enabling_error_explainer_does_not_grant_model_permission(tmp_path):
    client = FakeModelClient(response=ModelResponse(VALID_EXPLANATION))
    host = create_host(make_config(tmp_path), model_client=client)

    assert host.permission_manager.list_grants("error_explainer") == []
    assert host.tool_registry.get_tool(MODEL_GENERATE_TOOL).required_permission is Permission.EXECUTE
    host.close()
