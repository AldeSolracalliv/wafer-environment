from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.agents.registry import AgentStatus
from app.agents.runtime import AgentContext, AgentRequest
from app.security.permissions import PermissionDenied
from app.tools.runtime_status import RUNTIME_STATUS_TOOL
from app.tools.system_info import SYSTEM_INFO_TOOL


FIRST_AGENT_READ_TOOLS = (RUNTIME_STATUS_TOOL, SYSTEM_INFO_TOOL)


def _check(name: str, status: str, summary: str, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "summary": summary, **details}


def _valid_runtime_snapshot(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    runtime = value.get("runtime")
    agents = value.get("agents")
    tools = value.get("tools")
    jobs = value.get("jobs_by_status")
    if not isinstance(runtime, Mapping) or not isinstance(runtime.get("version"), str):
        return False
    if not isinstance(runtime.get("status"), str):
        return False
    if not isinstance(agents, list) or not all(
        isinstance(agent, Mapping)
        and isinstance(agent.get("id"), str)
        and isinstance(agent.get("availability"), str)
        for agent in agents
    ):
        return False
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        return False
    return isinstance(jobs, Mapping) and "FAILED" in jobs and all(
        isinstance(status, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        for status, count in jobs.items()
    )


def _valid_system_info(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(value.get(key), str) and bool(value[key].strip())
        for key in ("operating_system", "python_version", "architecture")
    )


class FirstAgent:
    """Read-only, deterministic Wafer runtime health inspector."""

    id = "first"
    name = "First Agent"
    description = "Inspects Wafer runtime health using read-only registered tools."
    capabilities: tuple[str, ...] = ()
    status = AgentStatus.AVAILABLE

    def execute(self, request: AgentRequest, context: AgentContext) -> dict[str, Any]:
        if request.task != "wafer.health_check":
            raise ValueError("unsupported task; expected 'wafer.health_check'")
        if not isinstance(request.context, Mapping):
            raise ValueError("context must be an object")
        unknown_options = set(request.context) - {"include_system_info"}
        if unknown_options:
            raise ValueError(f"unsupported health-check option: {next(iter(unknown_options))!r}")
        include_system_info = request.context.get("include_system_info", False)
        if not isinstance(include_system_info, bool):
            raise ValueError("include_system_info must be a boolean")

        checks: list[dict[str, Any]] = []
        overall_status = "unknown"
        try:
            snapshot = context.call_tool(RUNTIME_STATUS_TOOL)
        except PermissionDenied:
            checks.append(_check("wafer_runtime", "unknown", "Runtime status access was denied."))
        except KeyError:
            checks.append(_check("wafer_runtime", "unknown", "Runtime status tool is unavailable."))
        except Exception:
            checks.append(_check("wafer_runtime", "unknown", "Runtime status inspection failed."))
        else:
            if not _valid_runtime_snapshot(snapshot):
                checks.append(_check("wafer_runtime", "unknown", "Runtime status returned malformed data."))
            else:
                runtime = snapshot["runtime"]
                runtime_ok = runtime["status"] == "ONLINE"
                failed_jobs = snapshot["jobs_by_status"].get("FAILED", 0)
                checks.append(_check(
                    "wafer_runtime",
                    "healthy" if runtime_ok else "degraded",
                    "Wafer is online." if runtime_ok else "Wafer is not online.",
                    version=runtime["version"],
                    runtime_status=runtime["status"],
                    agent_count=len(snapshot["agents"]),
                    tool_count=len(snapshot["tools"]),
                ))
                jobs_ok = failed_jobs == 0
                checks.append(_check(
                    "jobs",
                    "healthy" if jobs_ok else "degraded",
                    "No failed jobs are recorded." if jobs_ok else "Failed jobs are recorded.",
                    counts=dict(snapshot["jobs_by_status"]),
                ))
                overall_status = "healthy" if runtime_ok and jobs_ok else "degraded"

        if include_system_info:
            try:
                system_info = context.call_tool(SYSTEM_INFO_TOOL)
            except PermissionDenied:
                checks.append(_check("host_system", "unknown", "System information access was denied."))
            except KeyError:
                checks.append(_check("host_system", "unknown", "System information tool is unavailable."))
            except Exception:
                checks.append(_check("host_system", "unknown", "System information inspection failed."))
            else:
                if not _valid_system_info(system_info):
                    checks.append(_check("host_system", "unknown", "System information returned malformed data."))
                else:
                    host_facts = {
                        key: system_info[key]
                        for key in ("operating_system", "python_version", "architecture")
                    }
                    checks.append(_check("host_system", "healthy", "Host information is available.", **host_facts))
            if checks[-1]["name"] == "host_system" and checks[-1]["status"] == "unknown" and overall_status == "healthy":
                overall_status = "degraded"

        summary = {
            "healthy": "Wafer runtime checks passed.",
            "degraded": "One or more requested Wafer runtime checks need attention.",
            "unknown": "Wafer runtime health could not be determined.",
        }[overall_status]
        return {
            "overall_status": overall_status,
            "summary": summary,
            "checks": checks,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
