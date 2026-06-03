from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.review.pr_context import PullRequestToolContext
from app.review.schema import (
    CheckConclusion,
    FindingSeverity,
    ReviewFinding,
    ValidatedReviewPayload,
)
from app.storage.runs import ReviewRun

CHECK_RUN_NAME = "MES PR Reviewer"
MAX_INLINE_COMMENTS = 3
MAX_CHECK_ANNOTATIONS = 50


class GitHubPublicationClient(Protocol):
    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, Any]: ...

    async def create_check_run(
        self,
        *,
        owner: str,
        repo: str,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def update_check_run(
        self,
        *,
        owner: str,
        repo: str,
        check_run_id: int,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def list_pull_request_reviews(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, Any]]: ...

    async def create_pull_request_review(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PublicationResult:
    status: str
    check_run_id: int | None = None
    check_run_url: str | None = None
    review_id: int | None = None
    review_url: str | None = None
    inline_comments: int = 0
    review_skipped: bool = False
    review_skip_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "check_run_id": self.check_run_id,
            "check_run_url": self.check_run_url,
            "review_id": self.review_id,
            "review_url": self.review_url,
            "inline_comments": self.inline_comments,
            "review_skipped": self.review_skipped,
            "review_skip_reason": self.review_skip_reason,
            "error": self.error,
        }


async def publish_validated_review(
    *,
    client: GitHubPublicationClient,
    pr_context: PullRequestToolContext,
    run: ReviewRun,
    validated: ValidatedReviewPayload,
) -> PublicationResult:
    head_sha = pr_context.head_sha or run.head_sha
    external_id = _external_id(
        repository=pr_context.repository,
        number=pr_context.number,
        head_sha=head_sha,
    )
    marker = _publication_marker(
        repository=pr_context.repository,
        number=pr_context.number,
        head_sha=head_sha,
    )
    check_run = await _upsert_check_run(
        client=client,
        pr_context=pr_context,
        run=run,
        validated=validated,
        head_sha=head_sha,
        external_id=external_id,
    )
    review, review_skipped, review_skip_reason = await _create_review_once(
        client=client,
        pr_context=pr_context,
        run=run,
        validated=validated,
        head_sha=head_sha,
        marker=marker,
    )
    return PublicationResult(
        status="published",
        check_run_id=_int_or_none(check_run.get("id")),
        check_run_url=_str_or_none(check_run.get("html_url")),
        review_id=_int_or_none(review.get("id")) if review else None,
        review_url=_str_or_none(review.get("html_url")) if review else None,
        inline_comments=len(_inline_findings(validated.publishable_findings)),
        review_skipped=review_skipped,
        review_skip_reason=review_skip_reason,
    )


def skipped_publication(reason: str) -> PublicationResult:
    return PublicationResult(status="skipped", review_skipped=True, review_skip_reason=reason)


async def _upsert_check_run(
    *,
    client: GitHubPublicationClient,
    pr_context: PullRequestToolContext,
    run: ReviewRun,
    validated: ValidatedReviewPayload,
    head_sha: str,
    external_id: str,
) -> dict[str, Any]:
    body = _check_run_body(
        run=run,
        validated=validated,
        head_sha=head_sha,
        external_id=external_id,
    )
    existing = await client.list_check_runs_for_ref(
        owner=pr_context.owner,
        repo=pr_context.repo,
        ref=head_sha,
    )
    matching = _find_existing_check_run(existing.get("check_runs"), external_id=external_id)
    if matching is not None and isinstance(matching.get("id"), int):
        update_body = {key: value for key, value in body.items() if key != "head_sha"}
        return await client.update_check_run(
            owner=pr_context.owner,
            repo=pr_context.repo,
            check_run_id=matching["id"],
            body=update_body,
        )
    return await client.create_check_run(
        owner=pr_context.owner,
        repo=pr_context.repo,
        body=body,
    )


async def _create_review_once(
    *,
    client: GitHubPublicationClient,
    pr_context: PullRequestToolContext,
    run: ReviewRun,
    validated: ValidatedReviewPayload,
    head_sha: str,
    marker: str,
) -> tuple[dict[str, Any] | None, bool, str | None]:
    reviews = await client.list_pull_request_reviews(
        owner=pr_context.owner,
        repo=pr_context.repo,
        number=pr_context.number,
    )
    if any(marker in str(review.get("body") or "") for review in reviews):
        return None, True, "review_already_published_for_head_sha"

    body = _review_body(run=run, validated=validated, marker=marker)
    review_payload = {
        "commit_id": head_sha,
        "body": body,
        "event": validated.review_event.value,
        "comments": [
            _review_comment_payload(finding)
            for finding in _inline_findings(validated.publishable_findings)
        ],
    }
    review = await client.create_pull_request_review(
        owner=pr_context.owner,
        repo=pr_context.repo,
        number=pr_context.number,
        body=review_payload,
    )
    return review, False, None


def _check_run_body(
    *,
    run: ReviewRun,
    validated: ValidatedReviewPayload,
    head_sha: str,
    external_id: str,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "name": CHECK_RUN_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": _check_conclusion(validated.check_conclusion),
        "external_id": external_id,
        "completed_at": now,
        "output": {
            "title": _check_title(validated),
            "summary": _check_summary(run=run, validated=validated),
            "text": _check_text(validated),
            "annotations": _check_annotations(validated.publishable_findings),
        },
    }


def _review_body(
    *,
    run: ReviewRun,
    validated: ValidatedReviewPayload,
    marker: str,
) -> str:
    lines = [
        marker,
        "Revisei o PR automaticamente.",
        "",
        f"- {len(validated.publishable_findings)} comentario(s) inline publicavel(is).",
        f"- {len(validated.summary_findings)} ponto(s) para checar no resumo.",
        f"- {len(validated.discarded_findings)} finding(s) descartado(s) pelo validador.",
        f"- Conclusao do check: `{validated.check_conclusion.value}`.",
        "",
        f"Run: `{run.run_id}`. Commit: `{run.head_sha[:12]}`.",
    ]
    if validated.summary_findings:
        lines.extend(["", "Pontos para checar:"])
        for finding in validated.summary_findings[:5]:
            lines.append(f"- **{finding.title}** em `{finding.path}`: {finding.body}")
    return "\n".join(lines)


def _review_comment_payload(finding: ReviewFinding) -> dict[str, Any]:
    if finding.line is None or finding.side is None:
        raise ValueError("publishable finding must have line and side")
    return {
        "path": finding.path,
        "line": finding.line,
        "side": finding.side,
        "body": _inline_comment_body(finding),
    }


def _inline_comment_body(finding: ReviewFinding) -> str:
    label = finding.severity.value.replace("_", " ")
    lines = [
        f"**{label}: {finding.title}**",
        "",
        finding.body,
    ]
    if finding.evidence:
        lines.extend(["", "Evidencia:"])
        lines.extend(f"- {item}" for item in finding.evidence[:3])
    if finding.suggested_fix:
        lines.extend(["", f"Sugestao: {finding.suggested_fix}"])
    return "\n".join(lines)


def _check_annotations(findings: Sequence[ReviewFinding]) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    for finding in findings:
        if len(annotations) >= MAX_CHECK_ANNOTATIONS:
            break
        if finding.line is None or finding.side != "RIGHT":
            continue
        annotations.append(
            {
                "path": finding.path,
                "start_line": finding.line,
                "end_line": finding.line,
                "annotation_level": _annotation_level(finding.severity),
                "title": _truncate(finding.title, 255),
                "message": _truncate(finding.body, 64_000),
                "raw_details": _truncate("\n".join(finding.evidence), 64_000),
            }
        )
    return annotations


def _check_title(validated: ValidatedReviewPayload) -> str:
    if validated.check_conclusion == CheckConclusion.SKIPPED:
        return "MES PR Reviewer: PR ignorado"
    if validated.check_conclusion == CheckConclusion.FAILURE:
        return "MES PR Reviewer: mudanças solicitadas"
    if validated.check_conclusion == CheckConclusion.NEUTRAL:
        return "MES PR Reviewer: comentarios gerados"
    return "MES PR Reviewer: sem achados bloqueantes"


def _check_summary(*, run: ReviewRun, validated: ValidatedReviewPayload) -> str:
    return (
        f"Run `{run.run_id}` revisou o commit `{run.head_sha}`. "
        f"{len(validated.publishable_findings)} achado(s) publicavel(is), "
        f"{len(validated.summary_findings)} ponto(s) de resumo, "
        f"{len(validated.discarded_findings)} descartado(s)."
    )


def _check_text(validated: ValidatedReviewPayload) -> str:
    if not (validated.publishable_findings or validated.summary_findings):
        return "Nenhum finding relevante foi validado para publicacao."
    lines: list[str] = []
    for finding in [*validated.publishable_findings, *validated.summary_findings][:10]:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        lines.append(f"- [{finding.severity.value}] {location} - {finding.title}")
    return "\n".join(lines)


def _inline_findings(findings: Sequence[ReviewFinding]) -> list[ReviewFinding]:
    return [
        finding
        for finding in findings
        if finding.line is not None and finding.side in {"LEFT", "RIGHT"}
    ][:MAX_INLINE_COMMENTS]


def _find_existing_check_run(
    check_runs: object,
    *,
    external_id: str,
) -> dict[str, Any] | None:
    if not isinstance(check_runs, list):
        return None
    for check_run in check_runs:
        if not isinstance(check_run, dict):
            continue
        if check_run.get("name") == CHECK_RUN_NAME and check_run.get("external_id") == external_id:
            return check_run
    return None


def _external_id(*, repository: str, number: int, head_sha: str) -> str:
    return f"mes-pr-reviewer:{repository}:{number}:{head_sha}"


def _publication_marker(*, repository: str, number: int, head_sha: str) -> str:
    return f"<!-- mes-pr-reviewer repository={repository} pr={number} head_sha={head_sha} -->"


def _check_conclusion(conclusion: CheckConclusion) -> str:
    if conclusion == CheckConclusion.FAILURE:
        return "failure"
    if conclusion == CheckConclusion.NEUTRAL:
        return "neutral"
    if conclusion == CheckConclusion.SKIPPED:
        return "skipped"
    return "success"


def _annotation_level(severity: FindingSeverity) -> str:
    if severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}:
        return "failure"
    if severity in {FindingSeverity.MEDIUM, FindingSeverity.LOW}:
        return "warning"
    return "notice"


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
