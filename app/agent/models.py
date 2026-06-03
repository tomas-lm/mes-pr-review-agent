from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class AgentTurn:
    index: int
    assistant_response: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    observations: list[ToolObservation] = field(default_factory=list)
    final_content: str = ""
    error: str | None = None


@dataclass
class AgentRunResult:
    final_payload: dict[str, Any]
    observations: list[ToolObservation] = field(default_factory=list)
    turns: list[AgentTurn] = field(default_factory=list)
    turns_used: int = 0
    error: str | None = None
