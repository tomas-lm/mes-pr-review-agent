from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.review.pr_context import PullRequestToolContext
from app.review.schema import (
    CheckConclusion,
    DiscardedFinding,
    DiscardReason,
    FindingSeverity,
    PullRequestReviewEvent,
    ReviewDecision,
    ReviewFinding,
    ValidatedReviewPayload,
)

PUBLISH_CONFIDENCE_THRESHOLD = 0.75
SUMMARY_CONFIDENCE_THRESHOLD = 0.50

_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|senha|secret|token|api_key)\b\s*[:=]\s*['\"]?[^\s,'\"]{8,}"),
)
_INTERNAL_REASONING_PATTERNS = (
    re.compile(r"<think\b", re.IGNORECASE),
    re.compile(r"chain[- ]of[- ]thought", re.IGNORECASE),
    re.compile(r"racioc[ií]nio interno", re.IGNORECASE),
    re.compile(r"passo a passo interno", re.IGNORECASE),
)


async def validate_agent_review_payload(
    payload: dict[str, Any],
    *,
    pr_context: PullRequestToolContext,
) -> ValidatedReviewPayload:
    raw_findings = payload.get("findings")
    findings_data = raw_findings if isinstance(raw_findings, list) else []
    discarded: list[DiscardedFinding] = []
    publishable: list[ReviewFinding] = []
    summary: list[ReviewFinding] = []
    seen_keys: set[tuple[str, int | None, str | None, str]] = set()

    if "findings" in payload and not isinstance(raw_findings, list):
        discarded.append(
            _discard(
                DiscardReason.INVALID_SCHEMA,
                {"findings": raw_findings},
                detail="findings must be a list",
            )
        )

    for raw_finding in findings_data:
        finding = _parse_finding(raw_finding, discarded)
        if finding is None:
            continue

        if _contains_secret(finding):
            discarded.append(
                _discard(DiscardReason.SECRET_DETECTED, finding.model_dump(mode="json"))
            )
            continue
        if _contains_internal_reasoning(finding):
            discarded.append(
                _discard(DiscardReason.INTERNAL_REASONING, finding.model_dump(mode="json"))
            )
            continue
        if not _has_evidence(finding):
            discarded.append(
                _discard(DiscardReason.MISSING_EVIDENCE, finding.model_dump(mode="json"))
            )
            continue
        if finding.confidence < SUMMARY_CONFIDENCE_THRESHOLD:
            discarded.append(
                _discard(DiscardReason.LOW_CONFIDENCE, finding.model_dump(mode="json"))
            )
            continue

        line_result = await _validate_line(finding, pr_context)
        if not line_result.get("valid"):
            discarded.append(
                _discard(
                    _discard_reason_from_line_result(line_result),
                    finding.model_dump(mode="json"),
                    detail=str(line_result.get("reason")),
                )
            )
            continue

        duplicate_key = _duplicate_key(finding)
        if duplicate_key in seen_keys:
            discarded.append(_discard(DiscardReason.DUPLICATE, finding.model_dump(mode="json")))
            continue
        seen_keys.add(duplicate_key)

        if (
            finding.confidence >= PUBLISH_CONFIDENCE_THRESHOLD
            and finding.severity != FindingSeverity.NIT
        ):
            publishable.append(finding)
        else:
            summary.append(finding)

    decision, conclusion, review_event = _derive_decision(
        raw_decision=_parse_decision(payload.get("decision")),
        publishable_findings=publishable,
        summary_findings=summary,
        discarded_findings=discarded,
        attempted_findings=bool(findings_data),
    )
    return ValidatedReviewPayload(
        decision=decision,
        publishable_findings=publishable,
        summary_findings=summary,
        discarded_findings=discarded,
        check_conclusion=conclusion,
        review_event=review_event,
    )


def _parse_finding(raw_finding: object, discarded: list[DiscardedFinding]) -> ReviewFinding | None:
    if not isinstance(raw_finding, dict):
        discarded.append(
            _discard(
                DiscardReason.INVALID_SCHEMA,
                {"value": raw_finding},
                detail="finding must be an object",
            )
        )
        return None
    try:
        finding = ReviewFinding.model_validate(raw_finding)
    except ValidationError as exc:
        discarded.append(
            _discard(
                DiscardReason.INVALID_SCHEMA,
                raw_finding,
                detail=exc.errors()[0]["msg"] if exc.errors() else "invalid finding schema",
            )
        )
        return None
    if not finding.path.strip() or finding.line is None:
        discarded.append(
            _discard(
                DiscardReason.LINE_NOT_IN_DIFF,
                finding.model_dump(mode="json"),
                detail="path and line are required",
            )
        )
        return None
    if finding.side not in {"LEFT", "RIGHT"}:
        discarded.append(
            _discard(
                DiscardReason.INVALID_SIDE,
                finding.model_dump(mode="json"),
                detail="side must be LEFT or RIGHT",
            )
        )
        return None
    return finding


async def _validate_line(
    finding: ReviewFinding,
    pr_context: PullRequestToolContext,
) -> dict[str, Any]:
    try:
        assert finding.line is not None
        assert finding.side is not None
        return await pr_context.validate_line_mapping(
            path=finding.path,
            line=finding.line,
            side=finding.side,
        )
    except RuntimeError as exc:
        return {"valid": False, "reason": "context_unavailable", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - validation should classify model/tool failures
        return {"valid": False, "reason": "line_not_in_diff", "error": str(exc)}


def _derive_decision(
    *,
    raw_decision: ReviewDecision,
    publishable_findings: list[ReviewFinding],
    summary_findings: list[ReviewFinding],
    discarded_findings: list[DiscardedFinding],
    attempted_findings: bool,
) -> tuple[ReviewDecision, CheckConclusion, PullRequestReviewEvent]:
    if raw_decision == ReviewDecision.SKIP:
        return ReviewDecision.SKIP, CheckConclusion.NEUTRAL, PullRequestReviewEvent.COMMENT
    has_blocking_finding = any(
        finding.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}
        for finding in publishable_findings
    )
    if has_blocking_finding:
        return (
            ReviewDecision.REQUEST_CHANGES,
            CheckConclusion.FAILURE,
            PullRequestReviewEvent.REQUEST_CHANGES,
        )
    if publishable_findings or summary_findings:
        return ReviewDecision.COMMENT, CheckConclusion.NEUTRAL, PullRequestReviewEvent.COMMENT
    if discarded_findings and attempted_findings:
        return ReviewDecision.COMMENT, CheckConclusion.NEUTRAL, PullRequestReviewEvent.COMMENT
    return ReviewDecision.APPROVE, CheckConclusion.SUCCESS, PullRequestReviewEvent.APPROVE


def _parse_decision(value: object) -> ReviewDecision:
    try:
        return ReviewDecision(str(value))
    except ValueError:
        return ReviewDecision.COMMENT


def _discard_reason_from_line_result(line_result: dict[str, Any]) -> DiscardReason:
    reason = str(line_result.get("reason") or "")
    try:
        return DiscardReason(reason)
    except ValueError:
        return DiscardReason.LINE_NOT_IN_DIFF


def _discard(
    reason: DiscardReason,
    finding: dict[str, Any],
    *,
    detail: str | None = None,
) -> DiscardedFinding:
    return DiscardedFinding(
        reason=reason,
        finding=_redact_sensitive(finding),
        detail=detail,
    )


def _duplicate_key(finding: ReviewFinding) -> tuple[str, int | None, str | None, str]:
    body_key = " ".join(finding.body.casefold().split())[:160]
    title_key = " ".join(finding.title.casefold().split())
    return (finding.path, finding.line, finding.side, f"{title_key}:{body_key}")


def _has_evidence(finding: ReviewFinding) -> bool:
    return any(item.strip() for item in finding.evidence)


def _contains_secret(finding: ReviewFinding) -> bool:
    return _matches_any_secret(str(finding.model_dump(mode="json")))


def _contains_internal_reasoning(finding: ReviewFinding) -> bool:
    text = str(finding.model_dump(mode="json"))
    return any(pattern.search(text) for pattern in _INTERNAL_REASONING_PATTERNS)


def _matches_any_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted
    return value
