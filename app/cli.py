import argparse
from pathlib import Path

from app.core.wafer import Wafer
from app.security.permissions import Permission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wafer Environment v0.1")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command")
    for command in ("status", "agents", "tools", "jobs"):
        subparsers.add_parser(command)
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
    wafer = Wafer(args.config)
    try:
        command = args.command or "status"
        if command == "status":
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
