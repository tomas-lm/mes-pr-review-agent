from __future__ import annotations

from typing import Any

from app.agent.models import ToolObservation
from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.review.pr_context import PullRequestToolContext
from app.state_machine.states import ReviewState
from app.state_machine.transitions import ALLOWED_TRANSITIONS
from app.storage.runs import ReviewRun
from app.tools.registry import ToolRegistry


def build_review_tool_registry(
    *,
    prompt_session: DynamicPromptSession,
    notes_writer: ReviewNotesWriter,
    pull_request_payload: dict[str, Any],
    pr_context: PullRequestToolContext,
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
            "base_sha": (pull_request.get("base") or {}).get("sha")
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

    async def list_changed_files(arguments: dict[str, object]) -> ToolObservation:
        if denied := _require_state(
            prompt_session,
            "list_changed_files",
            {ReviewState.COLLECT_CONTEXT, ReviewState.INVESTIGATE},
        ):
            return denied
        try:
            max_files = _bounded_int(arguments.get("max_files"), default=100, maximum=300)
            files, truncated = await pr_context.list_changed_files(max_files=max_files)
            return ToolObservation(
                tool_name="list_changed_files",
                ok=True,
                content=f"{len(files)} changed files returned for {pr_context.repository}",
                data={
                    "ok": True,
                    "summary": f"{len(files)} changed files returned",
                    "source": "github_api_cache",
                    "truncated": truncated,
                    "files": files,
                },
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return _tool_failure("list_changed_files", exc)

    async def get_diff_hunks(arguments: dict[str, object]) -> ToolObservation:
        if denied := _require_state(
            prompt_session,
            "get_diff_hunks",
            {ReviewState.COLLECT_CONTEXT, ReviewState.INVESTIGATE},
        ):
            return denied
        try:
            path_raw = arguments.get("path")
            path = str(path_raw).strip() if path_raw else None
            max_files = _bounded_int(arguments.get("max_files"), default=20, maximum=100)
            max_patch_chars = _bounded_int(
                arguments.get("max_patch_chars"),
                default=12_000,
                maximum=50_000,
            )
            files, truncated = await pr_context.get_diff_hunks(
                path=path,
                max_files=max_files,
                max_patch_chars=max_patch_chars,
            )
            target = f" for {path}" if path else ""
            return ToolObservation(
                tool_name="get_diff_hunks",
                ok=True,
                content=f"{len(files)} diff file entries returned{target}",
                data={
                    "ok": True,
                    "summary": f"{len(files)} diff file entries returned{target}",
                    "source": "github_api_cache",
                    "truncated": truncated,
                    "files": files,
                },
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return _tool_failure("get_diff_hunks", exc)

    async def read_file_at_ref(arguments: dict[str, object]) -> ToolObservation:
        if denied := _require_state(prompt_session, "read_file_at_ref", {ReviewState.INVESTIGATE}):
            return denied
        try:
            path = str(arguments.get("path") or "").strip()
            ref = str(arguments.get("ref") or "head").strip()
            max_chars = _bounded_int(arguments.get("max_chars"), default=30_000, maximum=80_000)
            data, truncated = await pr_context.read_file_at_ref(
                path=path,
                ref=ref,
                max_chars=max_chars,
            )
            return ToolObservation(
                tool_name="read_file_at_ref",
                ok=True,
                content=f"file read: {data.get('path')} at {data.get('requested_ref')}",
                data={
                    "ok": True,
                    "summary": f"file read: {data.get('path')}",
                    "source": "github_api_cache",
                    "truncated": truncated,
                    "file": data,
                },
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return _tool_failure("read_file_at_ref", exc)

    async def read_repo_rules(arguments: dict[str, object]) -> ToolObservation:
        if denied := _require_state(
            prompt_session,
            "read_repo_rules",
            {ReviewState.COLLECT_CONTEXT, ReviewState.INVESTIGATE},
        ):
            return denied
        try:
            paths_raw = arguments.get("paths")
            paths = [str(item) for item in paths_raw] if isinstance(paths_raw, list) else None
            ref = str(arguments.get("ref") or "base").strip()
            data = await pr_context.read_repo_rules(paths=paths, ref=ref)
            return ToolObservation(
                tool_name="read_repo_rules",
                ok=True,
                content=(
                    f"{len(data['files'])} repo rule files found; {len(data['missing'])} missing"
                ),
                data={
                    "ok": True,
                    "summary": f"{len(data['files'])} repo rule files found",
                    "source": "github_api_cache",
                    "truncated": any(item.get("truncated") for item in data["files"]),
                    **data,
                },
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return _tool_failure("read_repo_rules", exc)

    async def get_ci_status(_: dict[str, object]) -> ToolObservation:
        if denied := _require_state(
            prompt_session,
            "get_ci_status",
            {ReviewState.COLLECT_CONTEXT, ReviewState.INVESTIGATE, ReviewState.VALIDATE_FINDINGS},
        ):
            return denied
        try:
            data = await pr_context.get_ci_status()
            return ToolObservation(
                tool_name="get_ci_status",
                ok=True,
                content=f"{len(data['check_runs'])} check runs returned for {data['ref']}",
                data={
                    "ok": True,
                    "summary": f"{len(data['check_runs'])} check runs returned",
                    "source": "github_api_cache",
                    "truncated": False,
                    **data,
                },
            )
        except Exception as exc:  # noqa: BLE001 - tool errors are model observations
            return _tool_failure("get_ci_status", exc)

    registry.register("rewrite_state_prompt", rewrite_state_prompt)
    registry.register("append_review_observation", append_review_observation)
    registry.register("get_pr_metadata", get_pr_metadata)
    registry.register("get_state_machine", get_state_machine)
    registry.register("list_changed_files", list_changed_files)
    registry.register("get_diff_hunks", get_diff_hunks)
    registry.register("read_file_at_ref", read_file_at_ref)
    registry.register("read_repo_rules", read_repo_rules)
    registry.register("get_ci_status", get_ci_status)
    return registry


def _require_state(
    prompt_session: DynamicPromptSession,
    tool_name: str,
    allowed_states: set[ReviewState],
) -> ToolObservation | None:
    if prompt_session.state in allowed_states:
        return None
    return ToolObservation(
        tool_name=tool_name,
        ok=False,
        content=(
            f"{tool_name} is not allowed in state {prompt_session.state.value}. "
            "Use rewrite_state_prompt before calling it."
        ),
        data={
            "ok": False,
            "error": "state_not_allowed",
            "current_state": prompt_session.state.value,
            "allowed_states": [state.value for state in sorted(allowed_states, key=str)],
            "retryable": False,
        },
        error="state_not_allowed",
    )


def _bounded_int(
    value: object,
    *,
    default: int,
    maximum: int,
    minimum: int = 1,
) -> int:
    if value is None:
        return default
    number = int(value)
    return max(minimum, min(number, maximum))


def _tool_failure(tool_name: str, exc: Exception) -> ToolObservation:
    return ToolObservation(
        tool_name=tool_name,
        ok=False,
        content=f"{tool_name} failed: {exc}",
        data={
            "ok": False,
            "error": str(exc),
            "retryable": False,
        },
        error=str(exc),
    )
