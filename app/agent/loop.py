from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from app.agent.models import AgentRunResult, AgentTurn, ToolObservation
from app.agent.reasoning_protocol import parse_agent_response


class ModelClient(Protocol):
    async def complete(self, *, messages: list[dict[str, str]], system_prompt: str) -> str:
        """Return raw model text."""


ToolExecutor = Callable[[str, dict[str, object]], ToolObservation]
SystemPromptProvider = str | Callable[[], str]


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

    async def run(
        self, *, system_prompt: SystemPromptProvider, user_payload: str
    ) -> AgentRunResult:
        messages = [{"role": "user", "content": user_payload}]
        observations: list[ToolObservation] = []
        turns: list[AgentTurn] = []
        seen_tool_calls: set[tuple[str, str]] = set()

        for turn in range(1, self.max_turns + 1):
            current_system_prompt = system_prompt() if callable(system_prompt) else system_prompt
            raw_response = await self.model_client.complete(
                messages=messages,
                system_prompt=current_system_prompt,
            )
            parsed = parse_agent_response(raw_response)

            if parsed.invalid_tool_calls:
                observation = ToolObservation(
                    tool_name="agent_protocol",
                    ok=False,
                    content="invalid tool call: " + "; ".join(parsed.invalid_tool_calls),
                    error="invalid tool call",
                )
                observations.append(observation)
                turns.append(
                    AgentTurn(
                        index=turn,
                        assistant_response=parsed.sanitized_response,
                        observations=[observation],
                        error=observation.content,
                    )
                )
                messages.append({"role": "assistant", "content": parsed.sanitized_response})
                messages.append({"role": "user", "content": observation.content})
                continue

            if parsed.tool_calls:
                turn_observations: list[ToolObservation] = []
                for tool_call in parsed.tool_calls:
                    key = (tool_call.name, repr(sorted(tool_call.arguments.items())))
                    if key in seen_tool_calls:
                        error = f"repeated tool call: {tool_call.name}"
                        turns.append(
                            AgentTurn(
                                index=turn,
                                assistant_response=parsed.sanitized_response,
                                tool_calls=parsed.tool_calls,
                                observations=turn_observations,
                                error=error,
                            )
                        )
                        return AgentRunResult(
                            final_payload={},
                            observations=observations,
                            turns=turns,
                            turns_used=turn,
                            error=error,
                        )
                    seen_tool_calls.add(key)
                    observation = self.tool_executor(tool_call.name, tool_call.arguments)
                    observations.append(observation)
                    turn_observations.append(observation)
                turns.append(
                    AgentTurn(
                        index=turn,
                        assistant_response=parsed.sanitized_response,
                        tool_calls=parsed.tool_calls,
                        observations=turn_observations,
                    )
                )
                messages.append({"role": "assistant", "content": parsed.sanitized_response})
                messages.append(
                    {
                        "role": "user",
                        "content": "\n\n".join(
                            observation.content for observation in turn_observations
                        ),
                    }
                )
                continue

            if parsed.final_content:
                try:
                    final_payload = json.loads(parsed.final_content)
                except json.JSONDecodeError as exc:
                    error = f"final answer is not valid JSON: {exc.msg}"
                    turns.append(
                        AgentTurn(
                            index=turn,
                            assistant_response=parsed.sanitized_response,
                            final_content=parsed.final_content,
                            error=error,
                        )
                    )
                    return AgentRunResult(
                        final_payload={},
                        observations=observations,
                        turns=turns,
                        turns_used=turn,
                        error=error,
                    )
                if not isinstance(final_payload, dict):
                    error = "final JSON must be an object"
                    turns.append(
                        AgentTurn(
                            index=turn,
                            assistant_response=parsed.sanitized_response,
                            final_content=parsed.final_content,
                            error=error,
                        )
                    )
                    return AgentRunResult(
                        final_payload={},
                        observations=observations,
                        turns=turns,
                        turns_used=turn,
                        error=error,
                    )
                turns.append(
                    AgentTurn(
                        index=turn,
                        assistant_response=parsed.sanitized_response,
                        final_content=parsed.final_content,
                    )
                )
                return AgentRunResult(
                    final_payload=final_payload,
                    observations=observations,
                    turns=turns,
                    turns_used=turn,
                )

            error = "model returned neither tool call nor final answer"
            turns.append(
                AgentTurn(
                    index=turn,
                    assistant_response=parsed.sanitized_response,
                    error=error,
                )
            )
            return AgentRunResult(
                final_payload={},
                observations=observations,
                turns=turns,
                turns_used=turn,
                error=error,
            )

        return AgentRunResult(
            final_payload={},
            observations=observations,
            turns=turns,
            turns_used=self.max_turns,
            error="max turns reached",
        )
