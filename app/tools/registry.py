from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from app.agent.models import ToolObservation

ToolHandler = Callable[[dict[str, object]], ToolObservation | Awaitable[ToolObservation]]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        self._handlers[name] = handler

    async def call(self, name: str, arguments: dict[str, object]) -> ToolObservation:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolObservation(
                tool_name=name,
                ok=False,
                content=f"unknown tool: {name}",
                error="unknown tool",
            )
        observation = handler(arguments)
        if inspect.isawaitable(observation):
            return await observation
        return observation
