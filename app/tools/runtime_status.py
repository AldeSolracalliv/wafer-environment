from collections import Counter
from typing import Any, Callable

from app.agents.registry import AgentRegistry
from app.jobs.manager import JobManager, JobStatus
from app.security.permissions import Permission
from app.tools.registry import Tool, ToolRegistry


RUNTIME_STATUS_TOOL = "wafer.runtime_status"


def create_runtime_status_tool(
    version: str,
    get_status: Callable[[], str],
    agents: AgentRegistry,
    tools: ToolRegistry,
    jobs: JobManager,
) -> Tool:
    def runtime_status(parameters: dict[str, Any]) -> dict[str, Any]:
        if parameters:
            raise ValueError("wafer.runtime_status does not accept parameters")
        counts = Counter(job.status.value for job in jobs.list_jobs())
        return {
            "runtime": {"version": version, "status": get_status()},
            "agents": [
                {"id": agent.id, "availability": agent.status.value}
                for agent in agents.list_agents()
            ],
            "tools": sorted(tool.name for tool in tools.list_tools()),
            "jobs_by_status": {status.value: counts[status.value] for status in JobStatus},
        }

    return Tool(
        name=RUNTIME_STATUS_TOOL,
        description="Return a sanitized, read-only summary of Wafer runtime state.",
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        required_permission=Permission.READ,
        implementation=runtime_status,
    )
