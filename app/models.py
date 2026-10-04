from dataclasses import dataclass
from typing import Literal, Protocol


ModelRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ModelMessage:
    role: ModelRole
    content: str


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: ModelUsage | None = None
    model: str | None = None


class ModelError(Exception):
    """A safe, provider-neutral model failure suitable for AgentResult errors."""


class ModelClient(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
