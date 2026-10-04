import pytest

from app.agents.first import FirstAgent
from app.agents.registry import AgentStatus
from app.agents.request_echo import RequestEchoAgent
from app.agents.runtime import AgentRequest, AgentResultStatus
from app.core.config import WaferConfig
from app.core.wafer import Wafer
from app.host import create_host
from app.security.permissions import Permission
from app.tools.runtime_status import RUNTIME_STATUS_TOOL
from app.tools.system_info import SYSTEM_INFO_TOOL


def write_config(path, enabled_agents=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = '[wafer]\ndatabase_path = "wafer.db"\n'
    if enabled_agents is not None:
        content += '\n[host]\nenabled_agents = [' + ", ".join(
            f'"{agent_id}"' for agent_id in enabled_agents
        ) + ']\n'
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_and_empty_host_agent_configuration_default_to_none(tmp_path):
    missing_host = write_config(tmp_path / "missing.toml")
    empty_host = tmp_path / "empty.toml"
    empty_host.write_text(
        '[wafer]\ndatabase_path = "empty.db"\n\n[host]\nenabled_agents = []\n',
        encoding="utf-8",
    )

    assert WaferConfig.load(missing_host).host_enabled_agents == ()
    assert WaferConfig.load(empty_host).host_enabled_agents == ()
    assert WaferConfig().host_enabled_agents == ()


def test_host_attaches_only_known_configured_implementation_without_grants(tmp_path):
    config = write_config(tmp_path / "config.toml", ["first"])

    host = create_host(config)

    assert host.agent_registry.get_agent("first").__class__ is FirstAgent
    assert host.permission_manager.list_grants("first") == []
    host.close()


def test_request_echo_is_unavailable_until_host_explicitly_selects_it(tmp_path):
    config = write_config(tmp_path / "config.toml", [])
    unconfigured_host = create_host(config)

    unavailable = unconfigured_host.execute_agent(
        "request_echo", AgentRequest("echo-unavailable", "wafer.echo", context={"message": "hi"})
    )

    assert unavailable.status is AgentResultStatus.ERROR
    assert "Unknown agent" in unavailable.error
    assert unconfigured_host.agent_registry.get_agent("request_echo") is None
    unconfigured_host.close()

    write_config(config, ["request_echo"])
    configured_host = create_host(config)
    result = configured_host.execute_agent(
        "request_echo",
        AgentRequest(
            "echo-configured",
            "wafer.echo",
            context={"message": "hello"},
            configuration={"prefix": "host: "},
        ),
    )

    assert isinstance(configured_host.agent_registry.get_agent("request_echo"), RequestEchoAgent)
    assert result.status is AgentResultStatus.COMPLETED
    assert result.output == {"echo": "host: hello"}
    assert configured_host.permission_manager.list_grants("request_echo") == []
    configured_host.close()


def test_unknown_configured_agent_id_is_a_clear_host_configuration_error(tmp_path):
    config = write_config(tmp_path / "config.toml", ["unknown"])

    with pytest.raises(ValueError, match=r"\[host\]\.enabled_agents.*unknown.*first"):
        create_host(config)


def test_omitted_agent_identity_and_grants_remain_but_implementation_is_not_attached(tmp_path):
    config = write_config(tmp_path / "config.toml", [])
    wafer = Wafer(config)
    wafer.register_agent(FirstAgent())
    wafer.permission_manager.grant("first", Permission.READ, RUNTIME_STATUS_TOOL)
    grants_before = wafer.permission_manager.list_grants("first")
    wafer.close()

    host = create_host(config)
    result = host.execute_agent("first", AgentRequest("omitted", "wafer.health_check"))

    assert host.agent_registry.get_agent("first") is not None
    assert not callable(getattr(host.agent_registry.get_agent("first"), "execute", None))
    assert result.status is AgentResultStatus.ERROR
    assert "no executable implementation" in result.error
    assert host.permission_manager.list_grants("first") == grants_before
    host.close()


def test_configured_disabled_identity_stays_disabled_and_unavailable(tmp_path):
    config = write_config(tmp_path / "config.toml", [])
    wafer = Wafer(config)
    wafer.register_agent(FirstAgent())
    wafer.database.execute("UPDATE agents SET status = ? WHERE id = ?", (AgentStatus.DISABLED.value, "first"))
    wafer.close()
    write_config(config, ["first"])

    host = create_host(config)
    agent = host.agent_registry.get_agent("first")
    result = host.execute_agent("first", AgentRequest("disabled", "wafer.health_check"))

    assert agent.status is AgentStatus.DISABLED
    assert not callable(getattr(agent, "execute", None))
    assert result.status is AgentResultStatus.ERROR
    assert "not available" in result.error
    host.close()


def test_host_selection_preserves_exact_existing_grants(tmp_path):
    config = write_config(tmp_path / "config.toml", [])
    wafer = Wafer(config)
    wafer.register_agent(FirstAgent())
    wafer.permission_manager.grant("first", Permission.READ, RUNTIME_STATUS_TOOL)
    wafer.permission_manager.grant("first", Permission.READ, SYSTEM_INFO_TOOL)
    before = wafer.permission_manager.list_grants("first")
    wafer.close()
    write_config(config, ["first"])

    host = create_host(config)

    assert host.permission_manager.list_grants("first") == before
    assert all(tool != "*" for _, _, tool in before)
    assert all(permission is Permission.READ for _, permission, _ in before)
    host.close()


def test_selected_agent_without_tool_grant_remains_denied_and_audited(tmp_path):
    config = write_config(tmp_path / "config.toml", ["first"])
    host = create_host(config)

    result = host.execute_agent("first", AgentRequest("denied", "wafer.health_check"))
    decision = host.permission_manager.recent_decisions(1)[0]

    assert result.status is AgentResultStatus.COMPLETED
    assert result.output["overall_status"] == "unknown"
    assert decision.tool_name == RUNTIME_STATUS_TOOL and not decision.allowed
    host.close()


def test_invalid_host_enabled_agents_shape_is_rejected(tmp_path):
    config = tmp_path / "invalid.toml"
    config.write_text(
        '[wafer]\ndatabase_path = "wafer.db"\n\n[host]\nenabled_agents = "first"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\[host\]\.enabled_agents"):
        WaferConfig.load(config)
