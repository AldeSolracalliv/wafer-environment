from enum import IntEnum
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.database import Database


class Permission(IntEnum):
    READ = 1
    WRITE = 2
    EXECUTE = 3
    ADMIN = 4


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class PermissionDecision:
    timestamp: str
    agent_id: str
    tool_name: str
    permission: Permission | None
    allowed: bool
    reason: str


class PermissionManager:
    """Developer defaults plus persistent, deny-by-default agent grants."""

    def __init__(self, granted: tuple[str, ...], logger: logging.Logger, database: Database):
        self.granted = {Permission[value.upper()] for value in granted}
        self.logger = logger
        self.database = database

    def grant(self, agent_id: str, permission: Permission, tool_name: str = "*") -> None:
        if not self._agent_exists(agent_id):
            raise KeyError(f"Unknown agent: {agent_id}")
        self.database.execute(
            "INSERT OR IGNORE INTO agent_permissions (agent_id, permission, tool_name) VALUES (?, ?, ?)",
            (agent_id, permission.name, tool_name),
        )

    def revoke(self, agent_id: str, permission: Permission, tool_name: str = "*") -> bool:
        if not self._agent_exists(agent_id):
            raise KeyError(f"Unknown agent: {agent_id}")
        cursor = self.database.execute(
            "DELETE FROM agent_permissions WHERE agent_id = ? AND permission = ? AND tool_name = ?",
            (agent_id, permission.name, tool_name),
        )
        return cursor.rowcount > 0

    def list_grants(self, agent_id: str | None = None) -> list[tuple[str, Permission, str]]:
        if agent_id is None:
            rows = self.database.connection.execute(
                "SELECT agent_id, permission, tool_name FROM agent_permissions ORDER BY agent_id, permission, tool_name"
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                "SELECT agent_id, permission, tool_name FROM agent_permissions WHERE agent_id = ? ORDER BY permission, tool_name",
                (agent_id,),
            ).fetchall()
        return [(row["agent_id"], Permission[row["permission"]], row["tool_name"]) for row in rows]

    def _agent_exists(self, agent_id: str) -> bool:
        return self.database.connection.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone() is not None

    def decide(self, agent_id: str, tool_name: str, required: Permission | None) -> PermissionDecision:
        timestamp = datetime.now(timezone.utc).isoformat()
        if agent_id == "runtime":
            allowed = required is not None and any(grant >= required for grant in self.granted)
            reason = "developer policy grant" if allowed else "developer policy denies this permission"
        elif not self._agent_exists(agent_id):
            allowed, reason = False, "unknown agent identity"
        elif required is None:
            allowed, reason = False, "unknown tool has no executable permission"
        else:
            rows = self.database.connection.execute(
                "SELECT permission FROM agent_permissions WHERE agent_id = ? AND tool_name IN (?, '*')",
                (agent_id, tool_name),
            ).fetchall()
            grants = [Permission[row["permission"]] for row in rows]
            allowed = any(grant >= required for grant in grants)
            reason = "matching agent grant" if allowed else "no matching agent grant (deny by default)"
        decision = PermissionDecision(timestamp, agent_id, tool_name, required, allowed, reason)
        self.database.execute(
            "INSERT INTO permission_decisions (timestamp, agent_id, tool_name, permission, allowed, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, agent_id, tool_name, required.name if required else None, int(allowed), reason),
        )
        self.logger.info("permission.decision agent=%s tool=%s permission=%s allowed=%s reason=%s",
                         agent_id, tool_name, required.name if required else "UNKNOWN", allowed, reason)
        return decision

    def recent_decisions(self, limit: int = 20) -> list[PermissionDecision]:
        if limit < 1:
            raise ValueError("limit must be positive")
        rows = self.database.connection.execute(
            "SELECT * FROM permission_decisions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [PermissionDecision(row["timestamp"], row["agent_id"], row["tool_name"],
                                   Permission[row["permission"]] if row["permission"] else None,
                                   bool(row["allowed"]), row["reason"]) for row in rows]

    def require(self, requester: str, tool_name: str, required: Permission | None) -> None:
        decision = self.decide(requester, tool_name, required)
        if not decision.allowed:
            capability = required.name if required else "tool access"
            raise PermissionDenied(f"{requester!r} is not permitted to use {capability} for {tool_name!r}: {decision.reason}")
