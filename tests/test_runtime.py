from dataclasses import dataclass
from pathlib import Path
import logging

import pytest

from app.agents.registry import AgentRegistry, AgentStatus
from app.agents.first import FirstAgent
from app.agents.runtime import AgentLifecycle, AgentRequest, AgentResultStatus
from app.core.database import Database
from app.core.wafer import Wafer
from app.jobs.manager import JobManager, JobStatus
from app.security.permissions import Permission, PermissionDenied, PermissionManager
from app.tools.registry import Tool, ToolRegistry
from app.tools.runtime_status import RUNTIME_STATUS_TOOL
from app.tools.system_info import create_system_info_tool


def logger():
    return logging.getLogger("wafer.tests")


def test_agent_registry_and_persistence(tmp_path):
    db = Database(tmp_path / "test.db")
    registry = AgentRegistry(db, logger())
    @dataclass
    class SampleAgent:
        id: str = "sample"
        name: str = "Sample"
        description: str = "test agent"
        capabilities: tuple[str, ...] = ()
        status: AgentStatus = AgentStatus.AVAILABLE
    agent = SampleAgent()
    registry.register_agent(agent)
    assert registry.get_agent("sample") == agent
    assert registry.list_agents() == [agent]
    restored = AgentRegistry(db, logger())
    assert restored.get_agent("sample").name == "Sample"
    implementation = SampleAgent(description="updated implementation")
    restored.register_agent(implementation)
    assert restored.get_agent("sample") is implementation
    assert db.connection.execute("SELECT description FROM agents WHERE id = 'sample'").fetchone()[0] == "updated implementation"
    assert registry.unregister_agent("sample") == agent
    db.close()


def test_tool_registry_permission_and_system_info(tmp_path):
    db = Database(tmp_path / "test.db")
    permissions = PermissionManager(("READ",), logger(), db)
    tools = ToolRegistry(db, permissions, logger())
    info = create_system_info_tool()
    tools.register_tool(info)
    result = tools.execute_tool("system.info")
    assert set(result) == {"operating_system", "python_version", "architecture"}
    assert all(result.values())
    denied = Tool("danger", "denied", {}, Permission.EXECUTE, lambda _: "no")
    tools.register_tool(denied)
    with pytest.raises(PermissionDenied):
        tools.execute_tool("danger")
    assert tools.get_tool("system.info") == info
    assert len(tools.list_tools()) == 2
    assert tools.unregister_tool("danger") == denied
    db.close()


def test_job_lifecycle_persists(tmp_path):
    db = Database(tmp_path / "test.db")
    manager = JobManager(db, logger())
    created = manager.create_job("example", "sample")
    assert manager.get_job(created.id).status is JobStatus.PENDING
    running = manager.start_job(created.id)
    assert running.status is JobStatus.RUNNING and running.started_at
    complete = manager.complete_job(created.id, "done")
    assert complete.status is JobStatus.COMPLETED and complete.result == "done"
    assert manager.list_jobs() == [complete]
    assert JobManager(db, logger()).get_job(created.id) == complete
    cancelled = manager.create_job("cancel")
    assert manager.cancel_job(cancelled.id).status is JobStatus.CANCELLED
    failed = manager.create_job("fail")
    manager.start_job(failed.id)
    assert manager.fail_job(failed.id, "expected").error == "expected"
    db.close()


def test_wafer_startup_without_agents_and_cli(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n', encoding="utf-8")
    wafer = Wafer(config)
    assert wafer.status == "ONLINE"
    assert wafer.agent_registry.list_agents() == []
    assert {tool.name for tool in wafer.tool_registry.list_tools()} == {"system.info", "wafer.runtime_status"}
    assert "NOT CONFIGURED" in wafer.summary()
    wafer.close()


def test_agent_runtime_executes_registered_agent_and_tracks_lifecycle(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    agent = FirstAgent()
    wafer.agent_registry.register_agent(agent)
    wafer.permission_manager.grant("first", Permission.READ, RUNTIME_STATUS_TOOL)

    result = wafer.agent_runtime.execute("first", AgentRequest("req-1", "wafer.health_check"))

    assert result.request_id == "req-1"
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "healthy"
    assert result.error is None
    assert result.execution.lifecycle == (
        AgentLifecycle.CREATED,
        AgentLifecycle.INITIALIZING,
        AgentLifecycle.READY,
        AgentLifecycle.RUNNING,
        AgentLifecycle.COMPLETED,
        AgentLifecycle.IDLE,
    )
    assert result.execution.duration_ms >= 0
    wafer.close()


def test_agent_runtime_returns_structured_errors_and_recovers_to_idle(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)

    unknown = wafer.agent_runtime.execute("missing", AgentRequest("req-2", "task"))
    assert unknown.status is AgentResultStatus.ERROR
    assert unknown.error == "Unknown agent: missing"
    assert unknown.execution.lifecycle == (
        AgentLifecycle.CREATED,
        AgentLifecycle.INITIALIZING,
        AgentLifecycle.ERROR,
        AgentLifecycle.IDLE,
    )

    agent = FirstAgent()
    wafer.agent_registry.register_agent(agent)
    invalid = wafer.agent_runtime.execute("first", AgentRequest("req-3", " "))
    assert invalid.status is AgentResultStatus.ERROR
    assert invalid.error == "task must not be empty"

    class FailingAgent(FirstAgent):
        def execute(self, request, context):
            raise RuntimeError("execution failed")

    wafer.agent_registry.unregister_agent("first")
    wafer.agent_registry.register_agent(FailingAgent())
    failed = wafer.agent_runtime.execute("first", AgentRequest("req-4", "valid task"))
    assert failed.status is AgentResultStatus.ERROR
    assert failed.error == "execution failed"
    assert failed.execution.lifecycle[-3:] == (
        AgentLifecycle.RUNNING,
        AgentLifecycle.ERROR,
        AgentLifecycle.IDLE,
    )
    wafer.close()


def test_agent_runtime_routes_tool_calls_through_wafer_permissions(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)

    class ToolCallingAgent(FirstAgent):
        def execute(self, request, context):
            return context.call_tool("system.info")

    wafer.agent_registry.register_agent(ToolCallingAgent())
    denied = wafer.agent_runtime.execute("first", AgentRequest("req-4", "inspect"))
    assert denied.status is AgentResultStatus.ERROR
    assert "not permitted" in denied.error

    wafer.permission_manager.grant("first", Permission.READ, "system.info")
    allowed = wafer.agent_runtime.execute("first", AgentRequest("req-5", "inspect"))
    assert allowed.status is AgentResultStatus.COMPLETED
    assert set(allowed.output) == {"operating_system", "python_version", "architecture"}
    wafer.close()


@dataclass
class PermissionTestAgent:
    id: str = "policy-test"
    name: str = "Policy Test"
    description: str = "test identity"
    capabilities: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.AVAILABLE


def make_policy_wafer(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n', encoding="utf-8")
    wafer = Wafer(config)
    wafer.agent_registry.register_agent(PermissionTestAgent())
    return wafer, config


def test_unknown_agent_is_denied_and_audited(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    with pytest.raises(PermissionDenied):
        wafer.tool_registry.execute_tool("system.info", requester="missing-agent")
    decision = wafer.permission_manager.recent_decisions(1)[0]
    assert decision.agent_id == "missing-agent"
    assert decision.tool_name == "system.info" and not decision.allowed
    assert decision.reason == "unknown agent identity"
    wafer.close()


def test_new_agent_denied_by_default(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    with pytest.raises(PermissionDenied):
        wafer.tool_registry.execute_tool("system.info", requester="policy-test")
    assert "deny by default" in wafer.permission_manager.recent_decisions(1)[0].reason
    wafer.close()


def test_explicit_agent_grant_succeeds_and_can_be_revoked(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    wafer.permission_manager.grant("policy-test", Permission.READ, "system.info")
    result = wafer.tool_registry.execute_tool("system.info", requester="policy-test")
    assert set(result) == {"operating_system", "python_version", "architecture"}
    assert wafer.permission_manager.revoke("policy-test", Permission.READ, "system.info")
    with pytest.raises(PermissionDenied):
        wafer.tool_registry.execute_tool("system.info", requester="policy-test")
    wafer.close()


def test_denied_tool_implementation_never_runs(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    calls = []
    wafer.tool_registry.register_tool(Tool("test.action", "side effect", {}, Permission.WRITE, lambda _: calls.append(True)))
    with pytest.raises(PermissionDenied):
        wafer.tool_registry.execute_tool("test.action", requester="policy-test")
    assert calls == []
    wafer.close()


def test_decisions_persist_and_policies_survive_restart(tmp_path):
    wafer, config = make_policy_wafer(tmp_path)
    wafer.permission_manager.grant("policy-test", Permission.READ, "system.info")
    wafer.tool_registry.execute_tool("system.info", requester="policy-test")
    wafer.close()

    restarted = Wafer(config)
    assert restarted.agent_registry.get_agent("policy-test") is not None
    assert restarted.permission_manager.list_grants("policy-test") == [
        ("policy-test", Permission.READ, "system.info")
    ]
    record = restarted.permission_manager.recent_decisions(1)[0]
    assert record.agent_id == "policy-test" and record.tool_name == "system.info"
    assert record.permission is Permission.READ and record.allowed
    assert record.reason == "matching agent grant"
    assert record.timestamp
    restarted.close()


def test_runtime_system_info_developer_policy_remains_available(tmp_path):
    wafer, _ = make_policy_wafer(tmp_path)
    result = wafer.tool_registry.execute_tool("system.info")
    assert set(result) == {"operating_system", "python_version", "architecture"}
    assert wafer.permission_manager.recent_decisions(1)[0].allowed
    wafer.close()
