from pathlib import Path
import logging

from app.agents.registry import Agent, AgentRegistry
from app.agents.runtime import AgentRequest, AgentResult, AgentRuntime
from app.core.config import WaferConfig
from app.core.database import Database
from app.core.logging import configure_logging
from app.jobs.manager import JobManager
from app.memory.manager import MemoryManager
from app.security.permissions import PermissionManager
from app.tools.registry import ToolRegistry
from app.tools.runtime_status import create_runtime_status_tool
from app.tools.system_info import create_system_info_tool


class Wafer:
    def __init__(self, config_path: Path | str = "config.toml", database_path: Path | str | None = None):
        config_path = Path(config_path)
        self.config = WaferConfig.load(config_path)
        db_path = Path(database_path) if database_path is not None else self.config.database_path
        if not db_path.is_absolute() and database_path is None:
            db_path = config_path.parent / db_path
        self.logger: logging.Logger = configure_logging(self.config.log_level)
        self.database = Database(db_path)
        self.permission_manager = PermissionManager(self.config.granted_permissions, self.logger, self.database)
        self.agent_registry = AgentRegistry(self.database, self.logger)
        self.tool_registry = ToolRegistry(self.database, self.permission_manager, self.logger)
        self.agent_runtime = AgentRuntime(self.agent_registry, self.tool_registry, self.logger)
        self.job_manager = JobManager(self.database, self.logger)
        self.memory_manager = MemoryManager(self.database)
        self.status = "ONLINE"
        if self.tool_registry.get_tool("system.info") is None:
            self.tool_registry.register_tool(create_system_info_tool())
        if self.tool_registry.get_tool("wafer.runtime_status") is None:
            self.tool_registry.register_tool(create_runtime_status_tool(
                self.config.version,
                lambda: self.status,
                self.agent_registry,
                self.tool_registry,
                self.job_manager,
            ))
        self.logger.info("wafer.started version=%s", self.config.version)

    def close(self) -> None:
        self.database.close()

    def register_agent(self, agent: Agent) -> None:
        """Explicitly register an implementation with this Wafer host."""
        self.agent_registry.register_agent(agent)

    def execute_agent(self, agent_id: str, request: AgentRequest) -> AgentResult:
        """Submit a request through Wafer's generic agent runtime."""
        return self.agent_runtime.execute(agent_id, request)

    def summary(self) -> str:
        agents = ", ".join(agent.id for agent in self.agent_registry.list_agents()) or "None"
        tools = ", ".join(tool.name for tool in self.tool_registry.list_tools()) or "None"
        jobs = str(len(self.job_manager.list_jobs()))
        return "\n".join([
            "WAFER ENVIRONMENT", f"Version: {self.config.version}", f"Status: {self.status}", "",
            "Agents:", f"  {agents}", "", "Tools:", *[f"  {tool.name}" for tool in self.tool_registry.list_tools()],
            "", "Jobs:", f"  {jobs} job(s)", "", f"Memory:\n  {self.memory_manager.count()} entries", "Reasoning:\n  NOT CONFIGURED",
        ])
