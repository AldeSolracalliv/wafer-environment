import json

from app.agents.first import FIRST_AGENT_READ_TOOLS, FirstAgent
from app.agents.runtime import AgentRequest, AgentResultStatus
from app.core.wafer import Wafer
from app.security.permissions import Permission
from app.tools.registry import Tool
from app.tools.runtime_status import RUNTIME_STATUS_TOOL
from app.tools.system_info import SYSTEM_INFO_TOOL


def make_inspector(tmp_path, *, grant_system_info=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n', encoding="utf-8")
    wafer = Wafer(config)
    wafer.agent_registry.register_agent(FirstAgent())
    wafer.permission_manager.grant("first", Permission.READ, RUNTIME_STATUS_TOOL)
    if grant_system_info:
        wafer.permission_manager.grant("first", Permission.READ, SYSTEM_INFO_TOOL)
    return wafer


def inspect(wafer, request_id="health-1", **options):
    return wafer.agent_runtime.execute(
        "first", AgentRequest(request_id, "wafer.health_check", context=options)
    )


def replace_tool(wafer, name, implementation):
    original = wafer.tool_registry.get_tool(name)
    wafer.tool_registry.unregister_tool(name)
    wafer.tool_registry.register_tool(Tool(
        name=name,
        description=original.description,
        parameter_schema=original.parameter_schema,
        required_permission=original.required_permission,
        implementation=implementation,
    ))


def test_first_agent_reports_healthy_runtime_as_json_compatible(tmp_path):
    wafer = make_inspector(tmp_path)
    result = inspect(wafer)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.error is None
    assert result.output["overall_status"] == "healthy"
    assert result.output["summary"]
    assert {check["name"] for check in result.output["checks"]} == {"wafer_runtime", "jobs"}
    assert result.output["observed_at"]
    json.dumps(result.output)
    wafer.close()


def test_runtime_status_tool_exposes_only_sanitized_summary_fields(tmp_path):
    wafer = make_inspector(tmp_path)

    snapshot = wafer.tool_registry.execute_tool(RUNTIME_STATUS_TOOL, requester="runtime")

    assert set(snapshot) == {"runtime", "agents", "tools", "jobs_by_status"}
    assert snapshot["runtime"] == {"version": wafer.config.version, "status": "ONLINE"}
    assert snapshot["agents"] == [{"id": "first", "availability": "AVAILABLE"}]
    assert "wafer.runtime_status" in snapshot["tools"]
    assert snapshot["jobs_by_status"]["FAILED"] == 0
    assert not {"database_path", "permissions", "errors"} & set(snapshot)
    wafer.close()


def test_first_agent_reports_degraded_runtime_when_failed_jobs_exist(tmp_path):
    wafer = make_inspector(tmp_path)
    job = wafer.job_manager.create_job("example")
    wafer.job_manager.start_job(job.id)
    wafer.job_manager.fail_job(job.id, "private error details")

    result = inspect(wafer)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "degraded"
    jobs_check = next(check for check in result.output["checks"] if check["name"] == "jobs")
    assert jobs_check["status"] == "degraded"
    assert "private error details" not in json.dumps(result.output)
    wafer.close()


def test_first_agent_reports_unknown_when_runtime_tool_is_unavailable(tmp_path):
    wafer = make_inspector(tmp_path)
    wafer.tool_registry.unregister_tool(RUNTIME_STATUS_TOOL)

    result = inspect(wafer)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "unknown"
    assert "unavailable" in result.output["checks"][0]["summary"]
    assert wafer.permission_manager.recent_decisions(1)[0].tool_name == RUNTIME_STATUS_TOOL
    wafer.close()


def test_missing_optional_host_tool_is_reported_as_unknown(tmp_path):
    wafer = make_inspector(tmp_path)
    wafer.tool_registry.unregister_tool(SYSTEM_INFO_TOOL)

    result = inspect(wafer, include_system_info=True)

    host_check = next(check for check in result.output["checks"] if check["name"] == "host_system")
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "degraded"
    assert host_check["status"] == "unknown"
    assert "unavailable" in host_check["summary"]
    wafer.close()


def test_first_agent_reports_malformed_runtime_observation_as_unknown(tmp_path):
    wafer = make_inspector(tmp_path)
    replace_tool(wafer, RUNTIME_STATUS_TOOL, lambda _: {"runtime": "not-an-object"})

    result = inspect(wafer)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "unknown"
    assert "malformed" in result.output["checks"][0]["summary"]
    wafer.close()


def test_system_information_is_optional_and_successfully_reported_when_requested(tmp_path):
    wafer = make_inspector(tmp_path)

    default_result = inspect(wafer, "default")
    assert "host_system" not in {check["name"] for check in default_result.output["checks"]}

    requested_result = inspect(wafer, "host", include_system_info=True)
    host_check = next(check for check in requested_result.output["checks"] if check["name"] == "host_system")
    assert host_check["status"] == "healthy"
    assert host_check["operating_system"]
    wafer.close()


def test_denied_runtime_status_is_audited_and_reported_without_runtime_error(tmp_path):
    wafer = make_inspector(tmp_path, grant_system_info=False)
    wafer.permission_manager.revoke("first", Permission.READ, RUNTIME_STATUS_TOOL)

    result = inspect(wafer)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "unknown"
    assert "denied" in result.output["checks"][0]["summary"]
    decision = wafer.permission_manager.recent_decisions(1)[0]
    assert decision.tool_name == RUNTIME_STATUS_TOOL and not decision.allowed
    wafer.close()


def test_optional_system_information_permission_denial_is_a_finding(tmp_path):
    wafer = make_inspector(tmp_path, grant_system_info=False)

    result = inspect(wafer, include_system_info=True)

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "degraded"
    host_check = next(check for check in result.output["checks"] if check["name"] == "host_system")
    assert host_check["status"] == "unknown"
    assert wafer.permission_manager.recent_decisions(1)[0].tool_name == SYSTEM_INFO_TOOL
    wafer.close()


def test_expected_tool_exceptions_become_inspection_findings(tmp_path):
    wafer = make_inspector(tmp_path)
    original_runtime_status = wafer.tool_registry.get_tool(RUNTIME_STATUS_TOOL).implementation
    replace_tool(wafer, RUNTIME_STATUS_TOOL, lambda _: (_ for _ in ()).throw(RuntimeError("sensitive")))
    result = inspect(wafer)
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "unknown"
    assert "sensitive" not in json.dumps(result.output)

    replace_tool(wafer, RUNTIME_STATUS_TOOL, original_runtime_status)
    replace_tool(wafer, SYSTEM_INFO_TOOL, lambda _: (_ for _ in ()).throw(RuntimeError("sensitive")))
    host_result = inspect(wafer, "host", include_system_info=True)
    assert host_result.status is AgentResultStatus.COMPLETED
    assert host_result.output["overall_status"] == "degraded"
    host_check = next(check for check in host_result.output["checks"] if check["name"] == "host_system")
    assert host_check["status"] == "unknown"
    assert "sensitive" not in json.dumps(host_result.output)
    wafer.close()


def test_invalid_task_and_options_are_structured_runtime_errors(tmp_path):
    wafer = make_inspector(tmp_path)

    invalid_task = wafer.agent_runtime.execute("first", AgentRequest("bad-task", "anything"))
    invalid_option = inspect(wafer, "bad-option", include_system_info="yes")
    unknown_option = inspect(wafer, "unknown-option", surprise=True)

    assert invalid_task.status is AgentResultStatus.ERROR
    assert "unsupported task" in invalid_task.error
    assert invalid_option.status is AgentResultStatus.ERROR
    assert "boolean" in invalid_option.error
    assert unknown_option.status is AgentResultStatus.ERROR
    assert "unsupported health-check option" in unknown_option.error
    wafer.close()


def test_exact_read_permission_requirements_and_no_automatic_registration(tmp_path):
    config = tmp_path / "empty.toml"
    config.write_text('[wafer]\ndatabase_path = "empty.db"\n', encoding="utf-8")
    empty_wafer = Wafer(config)
    assert empty_wafer.agent_registry.list_agents() == []
    empty_wafer.close()

    wafer = make_inspector(tmp_path / "host")
    grants = wafer.permission_manager.list_grants("first")
    assert {(permission, tool) for _, permission, tool in grants} == {
        (Permission.READ, name) for name in FIRST_AGENT_READ_TOOLS
    }
    assert len(grants) == 2
    wafer.close()
