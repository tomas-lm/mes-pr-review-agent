from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.llm_client import OpenAICompatibleModelClient
from app.agent.loop import AgenticLoop, ModelClient
from app.config import Settings
from app.github.app_auth import GitHubAppAuth
from app.github.client import GitHubClient
from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.review.pr_context import build_pr_tool_context
from app.review.publisher import PublicationResult, publish_validated_review, skipped_publication
from app.review.trace import make_trace_snapshot, render_sanitized_trace
from app.review.validator import validate_agent_review_payload
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
        started_at = datetime.now(UTC)
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
            trace_markdown = render_sanitized_trace(
                run=run,
                snapshot=make_trace_snapshot(
                    started_at=started_at,
                    final_status="needs_human",
                    error="LLM_API_KEY is not configured",
                ),
            )
            notes_path = notes_writer.write(prompt_session, trace_markdown=trace_markdown)
            return ReviewServiceResult(status="needs_human", notes_path=str(notes_path))

        github_client, github_unavailable_reason = await self._github_client_for_run(run)
        pr_context = build_pr_tool_context(
            payload=payload,
            client=github_client,
            unavailable_reason=github_unavailable_reason,
        )
        registry = build_review_tool_registry(
            prompt_session=prompt_session,
            notes_writer=notes_writer,
            pull_request_payload=payload,
            pr_context=pr_context,
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
                        "Antes de ler diff, chame rewrite_state_prompt para COLLECT_CONTEXT.",
                        "Em COLLECT_CONTEXT, chame list_changed_files e read_repo_rules.",
                    ],
                },
                ensure_ascii=True,
            ),
        )
        notes_path = notes_writer.write(prompt_session)
        if result.error:
            if run.state != ReviewState.ERROR:
                _transition_run_to_terminal_error(run)
            trace_markdown = render_sanitized_trace(
                run=run,
                snapshot=make_trace_snapshot(
                    started_at=started_at,
                    final_status="error",
                    agent_result=result,
                    error=result.error,
                ),
            )
            notes_path = notes_writer.write(prompt_session, trace_markdown=trace_markdown)
            return ReviewServiceResult(
                status="error",
                notes_path=str(notes_path),
                error=result.error,
            )
        validated_payload = await validate_agent_review_payload(
            result.final_payload,
            pr_context=pr_context,
        )
        prompt_session.append_observation(
            category="validation",
            message=(
                "Validador processou a resposta final do agente: "
                f"{len(validated_payload.publishable_findings)} publicaveis, "
                f"{len(validated_payload.summary_findings)} para resumo, "
                f"{len(validated_payload.discarded_findings)} descartados."
            ),
            evidence=[
                f"decision={validated_payload.decision.value}",
                f"check_conclusion={validated_payload.check_conclusion.value}",
                f"review_event={validated_payload.review_event.value}",
            ],
        )
        try:
            publication_result = await self._publish_validated_payload(
                github_client=github_client,
                github_unavailable_reason=github_unavailable_reason,
                pr_context=pr_context,
                run=run,
                validated_payload=validated_payload,
            )
        except Exception as exc:  # noqa: BLE001 - GitHub publication failure is terminal
            if run.state != ReviewState.ERROR:
                _transition_run_to_terminal_error(run)
            publication_result = PublicationResult(status="error", error=str(exc))
            prompt_session.append_observation(
                category="publication",
                message=f"Falha ao publicar resultado no GitHub: {exc}",
                todo="Reexecutar a revisao depois de corrigir a integracao GitHub.",
            )
            trace_markdown = render_sanitized_trace(
                run=run,
                snapshot=make_trace_snapshot(
                    started_at=started_at,
                    final_status="error",
                    agent_result=result,
                    validated_payload=validated_payload,
                    publication_result=publication_result,
                    error=str(exc),
                ),
            )
            notes_path = notes_writer.write(prompt_session, trace_markdown=trace_markdown)
            return ReviewServiceResult(
                status="error",
                notes_path=str(notes_path),
                final_payload={
                    **validated_payload.model_dump(mode="json"),
                    "publication": publication_result.to_dict(),
                },
                error=str(exc),
            )
        if publication_result.status == "published":
            _transition_run_after_publication(run)
        prompt_session.append_observation(
            category="publication",
            message=(
                "Publicacao GitHub processada: "
                f"status={publication_result.status}, "
                f"check_run_id={publication_result.check_run_id}, "
                f"review_id={publication_result.review_id}."
            ),
            evidence=[
                f"inline_comments={publication_result.inline_comments}",
                f"review_skipped={publication_result.review_skipped}",
            ],
        )
        trace_markdown = render_sanitized_trace(
            run=run,
            snapshot=make_trace_snapshot(
                started_at=started_at,
                final_status="completed",
                agent_result=result,
                validated_payload=validated_payload,
                publication_result=publication_result,
            ),
        )
        notes_path = notes_writer.write(prompt_session, trace_markdown=trace_markdown)
        return ReviewServiceResult(
            status="completed",
            notes_path=str(notes_path),
            final_payload={
                **validated_payload.model_dump(mode="json"),
                "publication": publication_result.to_dict(),
            },
        )

    def _model_client_from_settings(self) -> ModelClient | None:
        if not self.settings.llm_api_key:
            return None
        return OpenAICompatibleModelClient(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_api_base_url,
            model=self.settings.llm_model,
        )

    async def _publish_validated_payload(
        self,
        *,
        github_client: GitHubClient | None,
        github_unavailable_reason: str | None,
        pr_context,
        run: ReviewRun,
        validated_payload,
    ) -> PublicationResult:
        if github_client is None:
            return skipped_publication(github_unavailable_reason or "github_client_unavailable")
        return await publish_validated_review(
            client=github_client,
            pr_context=pr_context,
            run=run,
            validated=validated_payload,
        )

    async def _github_client_for_run(
        self,
        run: ReviewRun,
    ) -> tuple[GitHubClient | None, str | None]:
        try:
            github_private_key = self.settings.github_private_key_value
        except OSError as exc:
            return None, f"could not read GITHUB_APP_PRIVATE_KEY_FILE: {exc}"
        if not (self.settings.github_app_id and github_private_key):
            return (
                None,
                "GITHUB_APP_ID and GitHub App private key are not configured",
            )
        try:
            auth = GitHubAppAuth(
                app_id=self.settings.github_app_id,
                private_key=github_private_key,
                api_base_url=self.settings.github_api_base_url,
            )
            token_data = await auth.create_installation_token(
                installation_id=run.installation_id,
                permissions={
                    "contents": "read",
                    "pull_requests": "write",
                    "issues": "write",
                    "checks": "write",
                },
            )
            token = token_data.get("token")
            if not isinstance(token, str) or not token:
                return None, "GitHub installation token response did not include token"
            return (
                GitHubClient(
                    token=token,
                    api_base_url=self.settings.github_api_base_url,
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent as tool context
            return None, f"could not create GitHub installation token: {exc}"


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
        "base_sha": (pull_request.get("base") or {}).get("sha")
        if isinstance(pull_request, dict)
        else None,
        "base_ref": (pull_request.get("base") or {}).get("ref")
        if isinstance(pull_request, dict)
        else None,
        "head_ref": (pull_request.get("head") or {}).get("ref")
        if isinstance(pull_request, dict)
        else None,
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


def _transition_run_after_publication(run: ReviewRun) -> None:
    if run.state == ReviewState.COMMENT_PLAN:
        run.transition_to(ReviewState.PUBLISH, reason="publishing validated review")
        run.transition_to(ReviewState.DONE, reason="published validated review")
        return
    if run.state == ReviewState.PUBLISH:
        run.transition_to(ReviewState.DONE, reason="published validated review")
