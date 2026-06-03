from app.agent.reasoning_protocol import parse_agent_response


def test_parse_valid_tool_call() -> None:
    parsed = parse_agent_response(
        '<think>secret reasoning</think><tool name="get_pr_metadata">{"number": 1}</tool>'
    )

    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].name == "get_pr_metadata"
    assert parsed.tool_calls[0].arguments == {"number": 1}
    assert "secret reasoning" not in parsed.sanitized_response


def test_parse_invalid_tool_json() -> None:
    parsed = parse_agent_response('<tool name="get_pr_metadata">{bad json}</tool>')

    assert parsed.tool_calls == []
    assert parsed.invalid_tool_calls


def test_parse_final() -> None:
    parsed = parse_agent_response('<final>{"decision":"comment"}</final>')

    assert parsed.final_content == '{"decision":"comment"}'
