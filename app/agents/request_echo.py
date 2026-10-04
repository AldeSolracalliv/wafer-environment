from collections.abc import Mapping
from typing import Any

from app.agents.registry import AgentStatus
from app.agents.runtime import AgentContext, AgentRequest


class RequestEchoAgent:
    """Small reference agent for inspecting request data and configuration."""

    id = "request_echo"
    name = "Request Echo Agent"
    description = "Returns a validated request message with an optional configured prefix."
    capabilities: tuple[str, ...] = ()
    status = AgentStatus.AVAILABLE

    def execute(self, request: AgentRequest, context: AgentContext) -> dict[str, Any]:
        if request.task != "wafer.echo":
            raise ValueError("unsupported task; expected 'wafer.echo'")
        if not isinstance(request.context, Mapping):
            raise ValueError("context must be an object")
        if set(request.context) != {"message"}:
            raise ValueError("context must contain only 'message'")
        message = request.context["message"]
        if not isinstance(message, str):
            raise ValueError("message must be a string")

        if not isinstance(request.configuration, Mapping):
            raise ValueError("configuration must be an object")
        unknown_options = set(request.configuration) - {"prefix"}
        if unknown_options:
            raise ValueError(f"unsupported configuration option: {next(iter(unknown_options))!r}")
        prefix = request.configuration.get("prefix", "")
        if not isinstance(prefix, str):
            raise ValueError("prefix must be a string")

        return {"echo": f"{prefix}{message}"}
