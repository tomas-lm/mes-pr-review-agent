from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.models import ToolCall

_TOOL_RE = re.compile(
    r"<tool\s+name=[\"'](?P<name>[^\"']+)[\"']\s*>(?P<body>.*?)</tool>",
    re.IGNORECASE | re.DOTALL,
)
_FINAL_RE = re.compile(r"<final\b[^>]*>(?P<body>.*?)</final>", re.IGNORECASE | re.DOTALL)
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ParsedAgentResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    invalid_tool_calls: list[str] = field(default_factory=list)
    final_content: str = ""
    sanitized_response: str = ""


def parse_agent_response(text: str) -> ParsedAgentResponse:
    tool_calls: list[ToolCall] = []
    invalid_tool_calls: list[str] = []

    for match in _TOOL_RE.finditer(text):
        name = match.group("name").strip()
        raw_arguments = match.group("body").strip()
        try:
            arguments: Any = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            invalid_tool_calls.append(f"{name}: invalid json: {exc.msg}")
            continue
        if not isinstance(arguments, dict):
            invalid_tool_calls.append(f"{name}: arguments must be a JSON object")
            continue
        tool_calls.append(ToolCall(name=name, arguments=arguments))

    final_chunks = [match.group("body").strip() for match in _FINAL_RE.finditer(text)]
    sanitized = _THINK_RE.sub("[redacted reasoning]", text).strip()
    return ParsedAgentResponse(
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        final_content="\n\n".join(final_chunks).strip(),
        sanitized_response=sanitized,
    )
