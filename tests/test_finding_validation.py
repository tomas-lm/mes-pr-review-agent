from __future__ import annotations

import anyio

from app.review.pr_context import build_pr_tool_context
from app.review.schema import (
    CheckConclusion,
    DiscardReason,
    PullRequestReviewEvent,
    ReviewDecision,
)
from app.review.validator import validate_agent_review_payload


class FakeGitHubPRClient:
    async def list_pull_request_files(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "filename": "app/example.py",
                "status": "modified",
                "patch": "@@ -2,3 +2,4 @@\n context\n-old = 1\n+new = 1\n+added = 2\n unchanged",
            }
        ]

    async def get_file_contents_at_ref(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> dict[str, object]:
        raise NotImplementedError

    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, object]:
        raise NotImplementedError


def pr_payload() -> dict[str, object]:
    return {
        "repository": {"full_name": "tomas-lm/mes-pr-review-agent"},
        "pull_request": {
            "number": 7,
            "head": {"sha": "head-sha", "ref": "feature/pr-review"},
            "base": {"sha": "base-sha", "ref": "main"},
        },
    }


def finding(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "severity": "high",
        "confidence": 0.91,
        "category": "bug",
        "path": "app/example.py",
        "line": 3,
        "side": "RIGHT",
        "title": "Incorrect value is now accepted",
        "body": "The added branch accepts an invalid value.",
        "evidence": ["The diff adds `new = 1` on line 3."],
    }
    data.update(overrides)
    return data


async def validate(payload: dict[str, object]):
    pr_context = build_pr_tool_context(payload=pr_payload(), client=FakeGitHubPRClient())
    return await validate_agent_review_payload(payload, pr_context=pr_context)


def test_high_confidence_high_severity_finding_requests_changes() -> None:
    async def run_test() -> None:
        result = await validate(
            {"decision": "comment", "summary": "Review done", "findings": [finding()]}
        )

        assert result.decision == ReviewDecision.REQUEST_CHANGES
        assert result.check_conclusion == CheckConclusion.FAILURE
        assert result.review_event == PullRequestReviewEvent.REQUEST_CHANGES
        assert len(result.publishable_findings) == 1
        assert result.discarded_findings == []

    anyio.run(run_test)


def test_medium_confidence_finding_goes_to_summary_only() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "request_changes",
                "summary": "Review done",
                "findings": [finding(severity="medium", confidence=0.6)],
            }
        )

        assert result.decision == ReviewDecision.COMMENT
        assert result.check_conclusion == CheckConclusion.NEUTRAL
        assert len(result.publishable_findings) == 0
        assert len(result.summary_findings) == 1

    anyio.run(run_test)


def test_invalid_severity_is_discarded_as_invalid_schema() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(severity="urgent")],
            }
        )

        assert result.publishable_findings == []
        assert result.discarded_findings[0].reason == DiscardReason.INVALID_SCHEMA

    anyio.run(run_test)


def test_line_outside_diff_is_discarded() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(line=99)],
            }
        )

        assert result.publishable_findings == []
        assert result.discarded_findings[0].reason == DiscardReason.LINE_NOT_IN_DIFF

    anyio.run(run_test)


def test_context_line_is_not_publishable_inline() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(line=5)],
            }
        )

        assert result.publishable_findings == []
        assert result.discarded_findings[0].reason == DiscardReason.LINE_NOT_CHANGED

    anyio.run(run_test)


def test_secret_in_comment_discards_and_redacts_finding() -> None:
    async def run_test() -> None:
        secret = "ghp_1234567890abcdefghijZZ"
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(body=f"Token leaked: {secret}")],
            }
        )

        assert result.publishable_findings == []
        discarded = result.discarded_findings[0]
        assert discarded.reason == DiscardReason.SECRET_DETECTED
        assert secret not in str(discarded.finding)
        assert "[REDACTED_SECRET]" in str(discarded.finding)

    anyio.run(run_test)


def test_duplicate_finding_is_discarded() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(), finding()],
            }
        )

        assert len(result.publishable_findings) == 1
        assert result.discarded_findings[0].reason == DiscardReason.DUPLICATE

    anyio.run(run_test)


def test_missing_evidence_is_discarded() -> None:
    async def run_test() -> None:
        result = await validate(
            {
                "decision": "comment",
                "summary": "Review done",
                "findings": [finding(evidence=[])],
            }
        )

        assert result.publishable_findings == []
        assert result.discarded_findings[0].reason == DiscardReason.MISSING_EVIDENCE

    anyio.run(run_test)


def test_skip_decision_maps_to_skipped_check_conclusion() -> None:
    async def run_test() -> None:
        result = await validate({"decision": "skip", "summary": "Draft PR", "findings": []})

        assert result.decision == ReviewDecision.SKIP
        assert result.check_conclusion == CheckConclusion.SKIPPED
        assert result.review_event == PullRequestReviewEvent.COMMENT

    anyio.run(run_test)
