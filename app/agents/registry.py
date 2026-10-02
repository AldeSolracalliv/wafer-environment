from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.core.database import Database


class AgentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"


class Agent(Protocol):
    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    status: AgentStatus


@dataclass(frozen=True)
class AgentMetadata:
    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    status: AgentStatus


class AgentRegistry:
    def __init__(self, database: Database, logger: logging.Logger):
        self.database, self.logger = database, logger
        self._agents: dict[str, Agent] = {}
        rows = database.connection.execute("SELECT * FROM agents").fetchall()
        for row in rows:
            self._agents[row["id"]] = AgentMetadata(row["id"], row["name"], row["description"], tuple(json.loads(row["capabilities"])), AgentStatus(row["status"]))

    def register_agent(self, agent: Agent) -> None:
        if agent.id in self._agents:
            raise ValueError(f"Agent already registered: {agent.id}")
        self._agents[agent.id] = agent
        self.database.execute("INSERT INTO agents VALUES (?, ?, ?, ?, ?)", (agent.id, agent.name, agent.description, json.dumps(agent.capabilities), agent.status.value))
        self.logger.info("agent.registered id=%s", agent.id)

    def unregister_agent(self, agent_id: str) -> Agent | None:
        agent = self._agents.pop(agent_id, None)
        if agent:
            self.database.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        return agent

    def get_agent(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[Agent]:
        return list(self._agents.values())
