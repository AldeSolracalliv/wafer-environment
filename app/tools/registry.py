from dataclasses import dataclass
import json
import logging
from typing import Any, Callable

from app.core.database import Database
from app.security.permissions import Permission, PermissionDenied, PermissionManager


class UnknownToolError(KeyError):
    """A tool name is unavailable after recording the access decision."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameter_schema: dict[str, Any]
    required_permission: Permission
    implementation: Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self, database: Database, permissions: PermissionManager, logger: logging.Logger):
        self.database, self.permissions, self.logger = database, permissions, logger
        self._tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        self.database.execute("INSERT OR REPLACE INTO tools VALUES (?, ?, ?, ?)", (tool.name, tool.description, json.dumps(tool.parameter_schema), tool.required_permission.name))
        self.logger.info("tool.registered name=%s", tool.name)

    def unregister_tool(self, name: str) -> Tool | None:
        tool = self._tools.pop(name, None)
        if tool:
            self.database.execute("DELETE FROM tools WHERE name = ?", (name,))
        return tool

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def execute_tool(self, name: str, parameters: dict[str, Any] | None = None, requester: str = "runtime") -> Any:
        tool = self.get_tool(name)
        if tool is None:
            decision = self.permissions.decide(requester, name, None)
            if decision.reason != "unknown tool has no executable permission":
                raise PermissionDenied(
                    f"{requester!r} is not permitted to use tool access for {name!r}: {decision.reason}"
                )
            raise UnknownToolError(f"Unknown tool: {name}")
        self.permissions.require(requester, name, tool.required_permission)
        self.logger.info("tool.execution name=%s requester=%s", name, requester)
        return tool.implementation(parameters or {})
