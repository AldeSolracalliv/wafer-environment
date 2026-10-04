"""Host-side composition for the built-in agents exposed by the local CLI."""

import os
from pathlib import Path

from app.agents.error_explainer import ErrorExplainerAgent
from app.agents.first import FirstAgent
from app.agents.request_echo import RequestEchoAgent
from app.agents.runtime import AgentImplementation
from app.core.config import WaferConfig
from app.core.wafer import Wafer
from app.models import ModelClient
from app.tools.model_generate import create_model_generation_tool


_HOST_AGENT_FACTORIES: dict[str, type[AgentImplementation]] = {
    FirstAgent.id: FirstAgent,
    RequestEchoAgent.id: RequestEchoAgent,
    ErrorExplainerAgent.id: ErrorExplainerAgent,
}


def create_host(
    config_path: Path | str = "config.toml",
    *,
    model_client: ModelClient | None = None,
) -> Wafer:
    """Create Wafer and attach only configured implementations/capabilities."""
    wafer = Wafer(config_path)
    try:
        enabled_agents = wafer.config.host_enabled_agents
        unknown = [agent_id for agent_id in enabled_agents if agent_id not in _HOST_AGENT_FACTORIES]
        if unknown:
            supported = ", ".join(sorted(_HOST_AGENT_FACTORIES)) or "none"
            raise ValueError(
                "Unknown agent ID(s) in [host].enabled_agents: "
                f"{', '.join(unknown)}. This host supports: {supported}."
            )
        if ErrorExplainerAgent.id in enabled_agents:
            if model_client is None:
                raise ValueError(
                    "Agent 'error_explainer' requires an explicitly configured ModelClient."
                )
            wafer.tool_registry.register_tool(create_model_generation_tool(model_client))
        elif model_client is not None:
            raise ValueError(
                f"A ModelClient was configured, but '{ErrorExplainerAgent.id}' is not enabled."
            )
        for agent_id in enabled_agents:
            wafer.register_agent(_HOST_AGENT_FACTORIES[agent_id]())
    except Exception:
        wafer.close()
        raise
    return wafer


def create_openai_host(
    config_path: Path | str = "config.toml",
    *,
    model: str | None = None,
) -> Wafer:
    """Explicitly compose the OpenAI adapter for an enabled ErrorExplainerAgent."""
    enabled_agents = WaferConfig.load(Path(config_path)).host_enabled_agents
    if ErrorExplainerAgent.id not in enabled_agents:
        raise ValueError(
            "Agent 'error_explainer' must be listed in [host].enabled_agents to use OpenAI."
        )
    selected_model = model or os.environ.get("WAFER_OPENAI_MODEL")
    if not isinstance(selected_model, str) or not selected_model.strip():
        raise ValueError("Set WAFER_OPENAI_MODEL or pass model= when composing the OpenAI host.")

    from app.providers.openai_client import OpenAIModelClient

    return create_host(config_path, model_client=OpenAIModelClient(selected_model))
