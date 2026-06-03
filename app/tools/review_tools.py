from __future__ import annotations

from typing import Any

from app.agent.models import ToolObservation
from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.state_machine.states import ReviewState
from app.state_machine.transitions import ALLOWED_TRANSITIONS
from app.storage.runs import ReviewRun
from app.tools.registry import ToolRegistry


def build_review_tool_registry(
    *,
    prompt_session: DynamicPromptSession,
    notes_writer: ReviewNotesWriter,
    pull_request_payload: dict[str, Any],
    run: ReviewRun | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()

    def rewrite_state_prompt(arguments: dict[str, object]) -> ToolObservation:
        try:
            target_state = ReviewState(str(arguments.get("state") or ""))
            state_prompt = str(arguments.get("state_prompt") or "").strip()
            reason = str(arguments.get("reason") or "").strip()
            if not state_prompt:
                raise ValueError("state_prompt is required")
            if not reason:
                raise ValueError("reason is required")
            content = prompt_session.rewrite_state_layer(
                target_state=target_state,
                state_prompt=state_prompt,
                reason=reason,
            )
            if run is not None and run.state != target_state:
                run.transition_to(target_state, reason=reason)
            notes_path = notes_writer.write(prompt_session)
            return ToolObservation(
                tool_name="rewrite_state_prompt",
                ok=True,
                content=f"{content}. Notes updated at {notes_path}",
                data={"state": prompt_session.state.value, "notes_path": str(notes_path)},
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return ToolObservation(
                tool_name="rewrite_state_prompt",
                ok=False,
                content=f"rewrite_state_prompt failed: {exc}",
                error=str(exc),
            )

    def append_review_observation(arguments: dict[str, object]) -> ToolObservation:
        category = str(arguments.get("category") or "note").strip()
        message = str(arguments.get("message") or "").strip()
        todo_raw = arguments.get("todo")
        evidence_raw = arguments.get("evidence")
        evidence = [str(item) for item in evidence_raw] if isinstance(evidence_raw, list) else []
        if not message:
            return ToolObservation(
                tool_name="append_review_observation",
                ok=False,
                content="append_review_observation failed: message is required",
                error="message is required",
            )
        prompt_session.append_observation(
            category=category,
            message=message,
            todo=str(todo_raw).strip() if todo_raw else None,
            evidence=evidence,
        )
        notes_path = notes_writer.write(prompt_session)
        return ToolObservation(
            tool_name="append_review_observation",
            ok=True,
            content=f"observation appended. Notes updated at {notes_path}",
            data={"notes_path": str(notes_path), "observations": len(prompt_session.observations)},
        )

    def get_pr_metadata(_: dict[str, object]) -> ToolObservation:
        pull_request = pull_request_payload.get("pull_request") or {}
        repository = pull_request_payload.get("repository") or {}
        metadata = {
            "action": pull_request_payload.get("action"),
            "repository": repository.get("full_name") if isinstance(repository, dict) else None,
            "number": pull_request.get("number") if isinstance(pull_request, dict) else None,
            "title": pull_request.get("title") if isinstance(pull_request, dict) else None,
            "body": pull_request.get("body") if isinstance(pull_request, dict) else None,
            "draft": pull_request.get("draft") if isinstance(pull_request, dict) else None,
            "head_sha": (pull_request.get("head") or {}).get("sha")
            if isinstance(pull_request, dict)
            else None,
            "base_ref": (pull_request.get("base") or {}).get("ref")
            if isinstance(pull_request, dict)
            else None,
            "head_ref": (pull_request.get("head") or {}).get("ref")
            if isinstance(pull_request, dict)
            else None,
        }
        return ToolObservation(
            tool_name="get_pr_metadata",
            ok=True,
            content=f"PR metadata: {metadata}",
            data=metadata,
        )

    def get_state_machine(_: dict[str, object]) -> ToolObservation:
        data = {
            "current_state": prompt_session.state.value,
            "allowed_transitions": [
                state.value for state in ALLOWED_TRANSITIONS[prompt_session.state]
            ],
        }
        return ToolObservation(
            tool_name="get_state_machine",
            ok=True,
            content=f"State machine: {data}",
            data=data,
        )

    registry.register("rewrite_state_prompt", rewrite_state_prompt)
    registry.register("append_review_observation", append_review_observation)
    registry.register("get_pr_metadata", get_pr_metadata)
    registry.register("get_state_machine", get_state_machine)
    return registry
