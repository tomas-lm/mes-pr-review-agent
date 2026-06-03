from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.llm_client import OpenAICompatibleModelClient
from app.agent.loop import AgenticLoop, ModelClient
from app.config import Settings
from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.state_machine.states import ReviewState
from app.storage.runs import ReviewRun
from app.tools.review_tools import build_review_tool_registry


@dataclass(frozen=True)
class ReviewServiceResult:
    status: str
    notes_path: str | None = None
    final_payload: dict[str, Any] | None = None
    error: str | None = None


class ReviewAgentService:
    def __init__(
        self,
        *,
        settings: Settings,
        model_client: ModelClient | None = None,
        notes_dir: str | Path | None = None,
    ) -> None:
        self.settings = settings
        self.model_client = model_client
        self.notes_dir = Path(notes_dir or settings.review_notes_dir)

    async def run_for_pull_request(
        self,
        *,
        run: ReviewRun,
        payload: dict[str, Any],
    ) -> ReviewServiceResult:
        runtime_context = _runtime_context_from_payload(run=run, payload=payload)
        prompt_session = DynamicPromptSession(
            run_id=run.run_id,
            state=ReviewState.RECEIVED,
            runtime_context=runtime_context,
        )
        notes_writer = ReviewNotesWriter(notes_dir=self.notes_dir)
        notes_path = notes_writer.write(prompt_session)

        model_client = self.model_client or self._model_client_from_settings()
        if model_client is None:
            run.transition_to(ReviewState.NEEDS_HUMAN, reason="LLM_API_KEY is not configured")
            prompt_session.rewrite_state_layer(
                target_state=ReviewState.NEEDS_HUMAN,
                reason="LLM_API_KEY is not configured",
                state_prompt=(
                    "A revisao agentica precisa de uma chave LLM para executar. "
                    "Configure LLM_API_KEY e rode novamente."
                ),
            )
            prompt_session.append_observation(
                category="configuration",
                message="LLM_API_KEY ausente; loop agentico nao foi chamado.",
                todo="Configurar LLM_API_KEY com a chave Telnyx/Kimi antes do teste real.",
            )
            notes_path = notes_writer.write(prompt_session)
            return ReviewServiceResult(status="needs_human", notes_path=str(notes_path))

        registry = build_review_tool_registry(
            prompt_session=prompt_session,
            notes_writer=notes_writer,
            pull_request_payload=payload,
            run=run,
        )
        loop = AgenticLoop(
            model_client=model_client,
            tool_executor=registry.call,
            max_turns=self.settings.agent_max_turns,
        )
        result = await loop.run(
            system_prompt=prompt_session.render_system_prompt,
            user_payload=json.dumps(
                {
                    "task": "Revise este pull request seguindo a maquina de estados.",
                    "run_id": run.run_id,
                    "pull_request": runtime_context,
                    "required_first_steps": [
                        "Chame get_state_machine.",
                        "Chame rewrite_state_prompt para TRIAGE.",
                        "Chame append_review_observation para registrar o plano inicial.",
                    ],
                },
                ensure_ascii=True,
            ),
        )
        notes_path = notes_writer.write(prompt_session)
        if result.error:
            if run.state != ReviewState.ERROR:
                _transition_run_to_terminal_error(run)
            return ReviewServiceResult(
                status="error",
                notes_path=str(notes_path),
                error=result.error,
            )
        return ReviewServiceResult(
            status="completed",
            notes_path=str(notes_path),
            final_payload=result.final_payload,
        )

    def _model_client_from_settings(self) -> ModelClient | None:
        if not self.settings.llm_api_key:
            return None
        return OpenAICompatibleModelClient(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_api_base_url,
            model=self.settings.llm_model,
        )


def _runtime_context_from_payload(*, run: ReviewRun, payload: dict[str, Any]) -> dict[str, Any]:
    pull_request = payload.get("pull_request") if isinstance(payload, dict) else {}
    repository = payload.get("repository") if isinstance(payload, dict) else {}
    return {
        "repository": run.repository,
        "pull_request_number": run.pull_request_number,
        "head_sha": run.head_sha,
        "action": run.action,
        "installation_id": run.installation_id,
        "title": pull_request.get("title") if isinstance(pull_request, dict) else None,
        "body": pull_request.get("body") if isinstance(pull_request, dict) else None,
        "draft": pull_request.get("draft") if isinstance(pull_request, dict) else None,
        "sender": (payload.get("sender") or {}).get("login")
        if isinstance(payload.get("sender"), dict)
        else None,
        "repository_private": repository.get("private") if isinstance(repository, dict) else None,
    }


def _transition_run_to_terminal_error(run: ReviewRun) -> None:
    if run.state == ReviewState.RECEIVED:
        run.transition_to(ReviewState.ERROR, reason="agentic loop failed")
        return
    while run.state not in {ReviewState.ERROR, ReviewState.DONE, ReviewState.NEEDS_HUMAN}:
        try:
            run.transition_to(ReviewState.ERROR, reason="agentic loop failed")
            return
        except ValueError:
            run.state = ReviewState.ERROR
            return
