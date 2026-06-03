from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.agent.models import AgentRunResult, ToolObservation
from app.agent.reasoning_protocol import parse_agent_response


class ModelClient(Protocol):
    async def complete(self, *, messages: list[dict[str, str]], system_prompt: str) -> str:
        """Return raw model text."""


ToolExecutor = Callable[[str, dict[str, object]], ToolObservation]


class AgenticLoop:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_executor: ToolExecutor,
        max_turns: int = 12,
    ) -> None:
        self.model_client = model_client
        self.tool_executor = tool_executor
        self.max_turns = max_turns

    async def run(self, *, system_prompt: str, user_payload: str) -> AgentRunResult:
        messages = [{"role": "user", "content": user_payload}]
        observations: list[ToolObservation] = []
        seen_tool_calls: set[tuple[str, str]] = set()

        for turn in range(1, self.max_turns + 1):
            raw_response = await self.model_client.complete(
                messages=messages,
                system_prompt=system_prompt,
            )
            parsed = parse_agent_response(raw_response)

            if parsed.invalid_tool_calls:
                return AgentRunResult(
                    final_payload={},
                    observations=observations,
                    turns_used=turn,
                    error="invalid tool call: " + "; ".join(parsed.invalid_tool_calls),
                )

            if parsed.tool_calls:
                for tool_call in parsed.tool_calls:
                    key = (tool_call.name, repr(sorted(tool_call.arguments.items())))
                    if key in seen_tool_calls:
                        return AgentRunResult(
                            final_payload={},
                            observations=observations,
                            turns_used=turn,
                            error=f"repeated tool call: {tool_call.name}",
                        )
                    seen_tool_calls.add(key)
                    observation = self.tool_executor(tool_call.name, tool_call.arguments)
                    observations.append(observation)
                    messages.append({"role": "assistant", "content": parsed.sanitized_response})
                    messages.append({"role": "user", "content": observation.content})
                continue

            if parsed.final_content:
                return AgentRunResult(
                    final_payload={"raw_final": parsed.final_content},
                    observations=observations,
                    turns_used=turn,
                )

            return AgentRunResult(
                final_payload={},
                observations=observations,
                turns_used=turn,
                error="model returned neither tool call nor final answer",
            )

        return AgentRunResult(
            final_payload={},
            observations=observations,
            turns_used=self.max_turns,
            error="max turns reached",
        )
