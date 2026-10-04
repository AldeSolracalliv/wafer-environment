from dataclasses import fields

from app.agents.first import FirstAgent
from app.agents.registry import AgentStatus
from app.agents.request_echo import RequestEchoAgent
from app.agents.runtime import (
    AgentContext,
    AgentLifecycle,
    AgentRequest,
    AgentResultStatus,
)
from app.core.wafer import Wafer


def make_wafer(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n', encoding="utf-8")
    return Wafer(config)


def test_agent_context_contains_capabilities_without_request_values():
    assert {field.name for field in fields(AgentContext)} == {"call_tool"}


def test_request_echo_is_independent_and_uses_generic_runtime(tmp_path):
    wafer = make_wafer(tmp_path)
    agent = RequestEchoAgent()
    request = AgentRequest(
        "echo-1",
        "wafer.echo",
        context={"message": "hello"},
        configuration={"prefix": "test: "},
        metadata={"source": "contract-test"},
    )
    wafer.register_agent(agent)

    result = wafer.execute_agent(agent.id, request)

    assert not issubclass(RequestEchoAgent, FirstAgent)
    assert result.request_id == request.request_id
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output == {"echo": "test: hello"}
    assert result.metadata == request.metadata
    assert result.execution.lifecycle == (
        AgentLifecycle.CREATED,
        AgentLifecycle.INITIALIZING,
        AgentLifecycle.READY,
        AgentLifecycle.RUNNING,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.IDLE,
    )
    assert wafer.permission_manager.list_grants(agent.id) == []
    wafer.close()


def test_request_echo_invalid_task_is_a_generic_structured_runtime_error(tmp_path):
    wafer = make_wafer(tmp_path)
    wafer.register_agent(RequestEchoAgent())

    result = wafer.execute_agent(
        "request_echo",
        AgentRequest("echo-invalid", "wafer.health_check"),
    )

    assert result.status is AgentResultStatus.ERROR
    assert "unsupported task" in result.error
    assert result.execution.lifecycle[-2:] == (AgentLifecycle.ERROR, AgentLifecycle.IDLE)
    wafer.close()


def test_request_echo_validates_context_and_configuration(tmp_path):
    wafer = make_wafer(tmp_path)
    wafer.register_agent(RequestEchoAgent())

    invalid_context = wafer.execute_agent(
        "request_echo",
        AgentRequest("echo-context", "wafer.echo", context={"message": 7}),
    )
    invalid_configuration = wafer.execute_agent(
        "request_echo",
        AgentRequest(
            "echo-config",
            "wafer.echo",
            context={"message": "hello"},
            configuration={"prefix": 7},
        ),
    )

    assert invalid_context.status is AgentResultStatus.ERROR
    assert "message must be a string" in invalid_context.error
    assert invalid_configuration.status is AgentResultStatus.ERROR
    assert "prefix must be a string" in invalid_configuration.error
    wafer.close()


def test_runtime_passes_original_request_and_only_wafer_capabilities_in_context(tmp_path):
    received = []

    class ContractProbe:
        id = "contract_probe"
        name = "Contract Probe"
        description = "Captures the generic runtime call."
        capabilities: tuple[str, ...] = ()
        status = AgentStatus.AVAILABLE

        def execute(self, request, context):
            received.append((request, context))
            return {"context": request.context, "configuration": request.configuration}

    wafer = make_wafer(tmp_path)
    wafer.register_agent(ContractProbe())
    request = AgentRequest(
        "probe-1",
        "probe",
        context={"caller_value": "original"},
        configuration={"agent_setting": "configured"},
    )

    result = wafer.execute_agent("contract_probe", request)

    assert result.status is AgentResultStatus.COMPLETED
    assert received[0][0] is request
    assert callable(received[0][1].call_tool)
    assert not hasattr(received[0][1], "values")
    assert result.output == {
        "context": {"caller_value": "original"},
        "configuration": {"agent_setting": "configured"},
    }
    wafer.close()
