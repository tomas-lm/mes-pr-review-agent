from __future__ import annotations

import anyio

from app.review.pr_context import build_pr_tool_context
from app.review.publisher import CHECK_RUN_NAME, publish_validated_review
from app.review.schema import ValidatedReviewPayload
from app.storage.runs import ReviewRun


class FakePublicationClient:
    def __init__(
        self,
        *,
        check_runs: list[dict[str, object]] | None = None,
        reviews: list[dict[str, object]] | None = None,
    ) -> None:
        self.check_runs = check_runs or []
        self.reviews = reviews or []
        self.created_check_runs: list[dict[str, object]] = []
        self.updated_check_runs: list[dict[str, object]] = []
        self.created_reviews: list[dict[str, object]] = []

    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, object]:
        return {"total_count": len(self.check_runs), "check_runs": self.check_runs}

    async def create_check_run(
        self,
        *,
        owner: str,
        repo: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        self.created_check_runs.append(body)
        return {"id": 10, "html_url": "https://github.com/check/10", **body}

    async def update_check_run(
        self,
        *,
        owner: str,
        repo: str,
        check_run_id: int,
        body: dict[str, object],
    ) -> dict[str, object]:
        payload = {"id": check_run_id, "html_url": "https://github.com/check/9", **body}
        self.updated_check_runs.append(payload)
        return payload

    async def list_pull_request_reviews(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, object]]:
        return self.reviews

    async def create_pull_request_review(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
        body: dict[str, object],
    ) -> dict[str, object]:
        self.created_reviews.append(body)
        return {"id": 20, "html_url": "https://github.com/review/20", **body}


def pr_payload() -> dict[str, object]:
    return {
        "repository": {"full_name": "tomas-lm/mes-pr-review-agent"},
        "pull_request": {
            "number": 7,
            "head": {"sha": "abc123", "ref": "feature/pr-review"},
            "base": {"sha": "base123", "ref": "main"},
        },
    }


def make_run() -> ReviewRun:
    return ReviewRun(
        run_id="run-123",
        delivery_id="delivery-123",
        event="pull_request",
        action="opened",
        repository="tomas-lm/mes-pr-review-agent",
        pull_request_number=7,
        head_sha="abc123",
        installation_id=123,
    )


def validated_payload() -> ValidatedReviewPayload:
    findings = [
        {
            "severity": "high",
            "confidence": 0.92,
            "category": "bug",
            "path": "app/example.py",
            "line": 10 + index,
            "side": "RIGHT",
            "title": f"Bug {index}",
            "body": "This can break the request flow.",
            "evidence": ["The diff adds this branch."],
        }
        for index in range(4)
    ]
    return ValidatedReviewPayload.model_validate(
        {
            "decision": "request_changes",
            "publishable_findings": findings,
            "summary_findings": [
                {
                    "severity": "medium",
                    "confidence": 0.65,
                    "category": "test",
                    "path": "tests/test_example.py",
                    "line": 30,
                    "side": "RIGHT",
                    "title": "Missing regression test",
                    "body": "The risky branch has no test.",
                    "evidence": ["No test covers the new branch."],
                }
            ],
            "discarded_findings": [],
            "check_conclusion": "failure",
            "review_event": "REQUEST_CHANGES",
        }
    )


def test_publish_validated_review_creates_check_run_and_grouped_review() -> None:
    async def run_test() -> None:
        client = FakePublicationClient()
        pr_context = build_pr_tool_context(payload=pr_payload(), client=None)

        result = await publish_validated_review(
            client=client,
            pr_context=pr_context,
            run=make_run(),
            validated=validated_payload(),
        )

        assert result.status == "published"
        assert result.check_run_id == 10
        assert result.review_id == 20
        assert result.inline_comments == 3
        check_body = client.created_check_runs[0]
        assert check_body["name"] == CHECK_RUN_NAME
        assert check_body["head_sha"] == "abc123"
        assert check_body["conclusion"] == "failure"
        assert check_body["external_id"] == (
            "mes-pr-reviewer:tomas-lm/mes-pr-review-agent:7:abc123"
        )
        output = check_body["output"]
        assert isinstance(output, dict)
        assert len(output["annotations"]) == 4
        review_body = client.created_reviews[0]
        assert review_body["event"] == "REQUEST_CHANGES"
        assert len(review_body["comments"]) == 3
        assert "mes-pr-reviewer" in str(review_body["body"])

    anyio.run(run_test)


def test_publish_updates_existing_check_run_and_skips_duplicate_review() -> None:
    async def run_test() -> None:
        marker = (
            "<!-- mes-pr-reviewer repository=tomas-lm/mes-pr-review-agent pr=7 head_sha=abc123 -->"
        )
        client = FakePublicationClient(
            check_runs=[
                {
                    "id": 9,
                    "name": CHECK_RUN_NAME,
                    "external_id": "mes-pr-reviewer:tomas-lm/mes-pr-review-agent:7:abc123",
                }
            ],
            reviews=[{"id": 19, "body": marker}],
        )
        pr_context = build_pr_tool_context(payload=pr_payload(), client=None)

        result = await publish_validated_review(
            client=client,
            pr_context=pr_context,
            run=make_run(),
            validated=validated_payload(),
        )

        assert result.status == "published"
        assert result.check_run_id == 9
        assert result.review_skipped is True
        assert result.review_skip_reason == "review_already_published_for_head_sha"
        assert client.created_check_runs == []
        assert len(client.updated_check_runs) == 1
        assert client.created_reviews == []

    anyio.run(run_test)
