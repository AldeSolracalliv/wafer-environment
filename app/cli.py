import argparse
import json
from pathlib import Path
from pprint import pformat
import sys
from typing import Any
from uuid import uuid4

from app.agents.runtime import AgentRequest, AgentResult, AgentResultStatus
from app.host import create_host
from app.security.permissions import Permission


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"invalid JSON context: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("context must be a JSON object")
    return parsed


def format_agent_result(result: AgentResult) -> str:
    lines = [f"Execution: {result.status.value}", f"Request ID: {result.request_id}"]
    if result.execution is not None:
        lines.append(f"Duration: {result.execution.duration_ms:.2f} ms")
        lines.append("Lifecycle: " + " -> ".join(state.value for state in result.execution.lifecycle))
    if result.status is AgentResultStatus.ERROR:
        lines.append(f"Error: {result.error or 'Agent execution failed.'}")
    else:
        lines.append("Result:")
        try:
            rendered = json.dumps(result.output, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            rendered = pformat(result.output, sort_dicts=False)
        lines.append(rendered)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wafer Environment v0.1")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command")
    for command in ("status", "agents", "tools", "jobs"):
        subparsers.add_parser(command)
    run = subparsers.add_parser("run", help="Submit a request to an agent")
    run.add_argument("agent_id")
    run.add_argument("task")
    run.add_argument("--context", type=_json_object, default={}, help="Request context as a JSON object")
    grant = subparsers.add_parser("grant", help="Grant an agent a permission")
    grant.add_argument("agent_id")
    grant.add_argument("permission", choices=[p.name for p in Permission])
    grant.add_argument("--tool", default="*", help="Limit the grant to this tool (default: all tools)")
    revoke = subparsers.add_parser("revoke", help="Revoke an agent permission")
    revoke.add_argument("agent_id")
    revoke.add_argument("permission", choices=[p.name for p in Permission])
    revoke.add_argument("--tool", default="*")
    decisions = subparsers.add_parser("decisions", help="Show recent permission decisions")
    decisions.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        wafer = create_host(args.config)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    try:
        command = args.command or "status"
        if command == "run":
            request = AgentRequest(
                request_id=str(uuid4()),
                task=args.task,
                context=args.context,
            )
            result = wafer.execute_agent(args.agent_id, request)
            print(format_agent_result(result))
            return 0 if result.status is AgentResultStatus.COMPLETED else 1
        elif command == "status":
            print(wafer.summary())
        elif command == "agents":
            agents = wafer.agent_registry.list_agents()
            if not agents:
                print("None")
            for agent in agents:
                print(f"{agent.id}: {agent.name} [{agent.status.value}]")
                grants = wafer.permission_manager.list_grants(agent.id)
                print("  Permissions:")
                print("\n".join(f"    {permission.name} on {tool}" for _, permission, tool in grants) or "    None (deny by default)")
        elif command == "tools":
            print("\n".join(f"{t.name}: {t.description} ({t.required_permission.name})" for t in wafer.tool_registry.list_tools()) or "None")
        elif command == "jobs":
            print("\n".join(f"{j.id}: {j.description} [{j.status.value}]" for j in wafer.job_manager.list_jobs()) or "None")
        elif command == "grant":
            permission = Permission[args.permission]
            wafer.permission_manager.grant(args.agent_id, permission, args.tool)
            print(f"Granted {permission.name} to {args.agent_id} on {args.tool}")
        elif command == "revoke":
            permission = Permission[args.permission]
            removed = wafer.permission_manager.revoke(args.agent_id, permission, args.tool)
            print(("Revoked" if removed else "No matching grant") + f" {permission.name} for {args.agent_id} on {args.tool}")
        elif command == "decisions":
            records = wafer.permission_manager.recent_decisions(args.limit)
            print("\n".join(
                f"{item.timestamp} agent={item.agent_id} tool={item.tool_name} "
                f"permission={item.permission.name if item.permission else 'UNKNOWN'} "
                f"result={'ALLOW' if item.allowed else 'DENY'} reason={item.reason}"
                for item in records
            ) or "No permission decisions")
    finally:
        wafer.close()
    return 0
