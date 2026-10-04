import json

import pytest

from app.agents.first import FirstAgent
from app.core.wafer import Wafer
from app.cli import main
from app.security.permissions import Permission
from app.tools.runtime_status import RUNTIME_STATUS_TOOL
from app.tools.system_info import SYSTEM_INFO_TOOL


def prepare_agent(config_path, *, grant_runtime=True, grant_system_info=False):
    wafer = Wafer(config_path)
    wafer.register_agent(FirstAgent())
    if grant_runtime:
        wafer.permission_manager.grant("first", Permission.READ, RUNTIME_STATUS_TOOL)
    if grant_system_info:
        wafer.permission_manager.grant("first", Permission.READ, SYSTEM_INFO_TOOL)
    wafer.close()


def test_cli_parses_json_request_context_and_runs_first_agent(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["first"]\n', encoding="utf-8")
    prepare_agent(config, grant_system_info=True)

    exit_code = main([
        "--config", str(config), "run", "first", "wafer.health_check",
        "--context", '{"include_system_info": true}',
    ])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Execution: COMPLETED" in output
    assert '"overall_status": "healthy"' in output
    assert '"name": "wafer_runtime"' in output
    assert '"name": "host_system"' in output
    assert "Duration:" in output
    assert "Lifecycle:" in output


def test_cli_rejects_non_object_json_context(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--config", str(tmp_path / "unused.toml"), "run", "first", "wafer.health_check", "--context", "[]"])
    assert error.value.code == 2


def test_cli_displays_invalid_agent_request_as_execution_error(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["first"]\n', encoding="utf-8")
    prepare_agent(config)

    exit_code = main(["--config", str(config), "run", "first", "unsupported.task"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Execution: ERROR" in output
    assert "unsupported task" in output


def test_cli_displays_unexpected_agent_execution_error(tmp_path, capsys, monkeypatch):
    import app.host as host

    class FailingAgent(FirstAgent):
        def execute(self, request, context):
            raise RuntimeError("expected test failure")

    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["first"]\n', encoding="utf-8")
    prepare_agent(config)
    monkeypatch.setitem(host._HOST_AGENT_FACTORIES, "first", FailingAgent)

    exit_code = main(["--config", str(config), "run", "first", "wafer.health_check"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Execution: ERROR" in output
    assert "expected test failure" in output


def test_cli_reports_permission_failure_as_completed_unknown_health(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["first"]\n', encoding="utf-8")
    prepare_agent(config, grant_runtime=False)

    exit_code = main(["--config", str(config), "run", "first", "wafer.health_check"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Execution: COMPLETED" in output
    assert '"overall_status": "unknown"' in output
    assert "access was denied" in output

    wafer = Wafer(config)
    decision = wafer.permission_manager.recent_decisions(1)[0]
    assert decision.tool_name == RUNTIME_STATUS_TOOL and not decision.allowed
    wafer.close()


def test_formatted_structured_result_remains_valid_json(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = ["first"]\n', encoding="utf-8")
    prepare_agent(config)

    assert main(["--config", str(config), "run", "first", "wafer.health_check"]) == 0
    output = capsys.readouterr().out
    result_text = output.split("Result:\n", 1)[1]
    result = json.loads(result_text)
    assert result["overall_status"] == "healthy"
    assert {check["status"] for check in result["checks"]} == {"healthy"}


def test_cli_non_run_commands_do_not_install_agents(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('[wafer]\ndatabase_path = "wafer.db"\n', encoding="utf-8")

    assert main(["--config", str(config), "agents"]) == 0

    assert capsys.readouterr().out.strip() == "None"
    wafer = Wafer(config)
    assert wafer.agent_registry.list_agents() == []
    wafer.close()
