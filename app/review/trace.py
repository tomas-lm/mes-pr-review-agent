from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.agent.models import AgentRunResult
from app.review.publisher import PublicationResult
from app.review.schema import ValidatedReviewPayload
from app.storage.runs import ReviewRun


@dataclass(frozen=True)
class ReviewTraceSnapshot:
    started_at: datetime
    finished_at: datetime
    final_status: str
    agent_result: AgentRunResult | None = None
    validated_payload: ValidatedReviewPayload | None = None
    publication_result: PublicationResult | None = None
    error: str | None = None


def render_sanitized_trace(*, run: ReviewRun, snapshot: ReviewTraceSnapshot) -> str:
    duration_ms = int((snapshot.finished_at - snapshot.started_at).total_seconds() * 1000)
    lines = [
        "## Trace sanitizado",
        "",
        "### Identificacao",
        "",
        f"- run_id: `{run.run_id}`",
        f"- delivery_id: `{run.delivery_id}`",
        f"- repositorio: `{run.repository}`",
        f"- pull_request: `{run.pull_request_number}`",
        f"- head_sha: `{run.head_sha}`",
        f"- evento: `{run.event}.{run.action}`",
        f"- estado_final: `{run.state.value}`",
        f"- status_final: `{snapshot.final_status}`",
        f"- inicio: `{_iso(snapshot.started_at)}`",
        f"- fim: `{_iso(snapshot.finished_at)}`",
        f"- latencia_ms: `{duration_ms}`",
        "",
        "### Transicoes",
        "",
    ]
    if run.transitions:
        for transition in run.transitions:
            lines.append(
                "- "
                f"`{transition.from_state.value}` -> `{transition.to_state.value}` "
                f"em `{_iso(transition.created_at)}`; motivo: {transition.reason}"
            )
    else:
        lines.append("- Nenhuma transicao registrada.")

    lines.extend(["", "### Loop agentico", ""])
    if snapshot.agent_result is None:
        lines.append("- Loop nao executado.")
    else:
        token_estimate = _estimate_tokens(snapshot.agent_result)
        lines.extend(
            [
                f"- turns_usados: `{snapshot.agent_result.turns_used}`",
                f"- tokens_estimados: `{token_estimate}`",
                "- custo_estimado_usd: `indisponivel_sem_usage_do_provedor`",
            ]
        )
        if snapshot.agent_result.error:
            lines.append(f"- erro_loop: `{snapshot.agent_result.error}`")
        tool_lines = _tool_call_lines(snapshot.agent_result)
        lines.extend(["", "Tool calls:"])
        lines.extend(tool_lines or ["- Nenhuma tool chamada."])
        error_lines = _tool_error_lines(snapshot.agent_result)
        lines.extend(["", "Erros de tool:"])
        lines.extend(error_lines or ["- Nenhum erro de tool registrado."])

    lines.extend(["", "### Validacao", ""])
    if snapshot.validated_payload is None:
        lines.append("- Validacao nao executada.")
    else:
        lines.extend(
            [
                f"- findings_publicaveis: `{len(snapshot.validated_payload.publishable_findings)}`",
                f"- findings_resumo: `{len(snapshot.validated_payload.summary_findings)}`",
                f"- findings_descartados: `{len(snapshot.validated_payload.discarded_findings)}`",
                f"- decisao: `{snapshot.validated_payload.decision.value}`",
                f"- check_conclusion: `{snapshot.validated_payload.check_conclusion.value}`",
                f"- review_event: `{snapshot.validated_payload.review_event.value}`",
            ]
        )

    lines.extend(["", "### Publicacao", ""])
    if snapshot.publication_result is None:
        lines.append("- Publicacao nao executada.")
    else:
        lines.extend(
            [
                f"- status: `{snapshot.publication_result.status}`",
                f"- check_run_id: `{snapshot.publication_result.check_run_id}`",
                f"- review_id: `{snapshot.publication_result.review_id}`",
                f"- comentarios_inline: `{snapshot.publication_result.inline_comments}`",
                f"- review_ignorado: `{snapshot.publication_result.review_skipped}`",
                f"- motivo_skip: `{snapshot.publication_result.review_skip_reason}`",
            ]
        )
        if snapshot.publication_result.error:
            lines.append(f"- erro_publicacao: `{snapshot.publication_result.error}`")

    lines.extend(["", "### Seguranca", ""])
    lines.extend(
        [
            "- Resposta bruta do modelo nao foi gravada.",
            "- Installation token nao foi gravado.",
            "- Secrets detectados pelo validador sao bloqueados antes da publicacao.",
        ]
    )
    if snapshot.error:
        lines.extend(["", "### Erro final", "", f"- `{snapshot.error}`"])
    return "\n".join(lines).strip()


def make_trace_snapshot(
    *,
    started_at: datetime,
    final_status: str,
    agent_result: AgentRunResult | None = None,
    validated_payload: ValidatedReviewPayload | None = None,
    publication_result: PublicationResult | None = None,
    error: str | None = None,
) -> ReviewTraceSnapshot:
    return ReviewTraceSnapshot(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        final_status=final_status,
        agent_result=agent_result,
        validated_payload=validated_payload,
        publication_result=publication_result,
        error=error,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _estimate_tokens(result: AgentRunResult) -> int:
    text = "".join(turn.assistant_response for turn in result.turns)
    text += "".join(observation.content for observation in result.observations)
    text += "".join(turn.final_content for turn in result.turns)
    return max(1, len(text) // 4) if text else 0


def _tool_call_lines(result: AgentRunResult) -> list[str]:
    lines: list[str] = []
    for turn in result.turns:
        for tool_call in turn.tool_calls:
            argument_keys = ", ".join(sorted(tool_call.arguments))
            suffix = f" args=[{argument_keys}]" if argument_keys else " args=[]"
            lines.append(f"- Turno {turn.index}: `{tool_call.name}`{suffix}")
    return lines


def _tool_error_lines(result: AgentRunResult) -> list[str]:
    lines: list[str] = []
    for turn in result.turns:
        if turn.error:
            lines.append(f"- Turno {turn.index}: `{turn.error}`")
        for observation in turn.observations:
            if not observation.ok or observation.error:
                detail = observation.error or "tool returned ok=false"
                lines.append(f"- Turno {turn.index}: `{observation.tool_name}` -> `{detail}`")
    return lines
