from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol

from app.agents.registry import Agent, AgentRegistry, AgentStatus
from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class AgentRequest:
    request_id: str
    task: str
    context: Mapping[str, Any] = field(default_factory=dict)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    call_tool: Callable[[str, dict[str, Any] | None], Any]


class AgentImplementation(Agent, Protocol):
    def execute(self, request: AgentRequest, context: AgentContext) -> Any: ...


class AgentLifecycle(str, Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    IDLE = "IDLE"


class AgentResultStatus(str, Enum):
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AgentExecution:
    lifecycle: tuple[AgentLifecycle, ...]
    duration_ms: float


@dataclass(frozen=True)
class AgentResult:
    request_id: str
    status: AgentResultStatus
    output: Any = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution: AgentExecution | None = None


class AgentRuntime:
    """Wafer-owned synchronous execution boundary for registered agents."""

    def __init__(self, agents: AgentRegistry, tools: ToolRegistry, logger: logging.Logger):
        self.agents = agents
        self.tools = tools
        self.logger = logger

    def execute(self, agent_id: str, request: AgentRequest) -> AgentResult:
        started = perf_counter()
        lifecycle = [AgentLifecycle.CREATED]
        try:
            self._transition(lifecycle, AgentLifecycle.INITIALIZING, request.request_id, agent_id)
            if not request.request_id.strip():
                raise ValueError("request_id must not be empty")
            if not request.task.strip():
                raise ValueError("task must not be empty")

            agent = self.agents.get_agent(agent_id)
            if agent is None:
                raise LookupError(f"Unknown agent: {agent_id}")
            if agent.status is not AgentStatus.AVAILABLE:
                raise ValueError(f"Agent is not available: {agent_id}")
            implementation = getattr(agent, "execute", None)
            if not callable(implementation):
                raise TypeError(f"Registered agent has no executable implementation: {agent_id}")

            self._transition(lifecycle, AgentLifecycle.READY, request.request_id, agent_id)
            context = AgentContext(
                call_tool=lambda name, parameters=None: self.tools.execute_tool(
                    name, parameters, requester=agent_id
                ),
            )
            self._transition(lifecycle, AgentLifecycle.RUNNING, request.request_id, agent_id)
            output = implementation(request, context)
            self._transition(lifecycle, AgentLifecycle.COMPLETED, request.request_id, agent_id)
            return AgentResult(
                request_id=request.request_id,
                status=AgentResultStatus.COMPLETED,
                output=output,
                metadata=request.metadata,
                execution=AgentExecution(tuple(lifecycle + [AgentLifecycle.IDLE]), (perf_counter() - started) * 1000),
            )
        except Exception as error:
            self._transition(lifecycle, AgentLifecycle.ERROR, request.request_id, agent_id)
            return AgentResult(
                request_id=request.request_id,
                status=AgentResultStatus.ERROR,
                error=str(error),
                metadata=request.metadata,
                execution=AgentExecution(tuple(lifecycle + [AgentLifecycle.IDLE]), (perf_counter() - started) * 1000),
            )

    def _transition(self, lifecycle: list[AgentLifecycle], state: AgentLifecycle,
                    request_id: str, agent_id: str) -> None:
        lifecycle.append(state)
        self.logger.info("agent.lifecycle agent=%s request=%s state=%s", agent_id, request_id, state.value)

