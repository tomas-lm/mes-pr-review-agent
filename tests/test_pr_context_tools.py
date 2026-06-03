from __future__ import annotations

import anyio

from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.review.pr_context import build_pr_tool_context
from app.state_machine.states import ReviewState
from app.tools.review_tools import build_review_tool_registry


class FakeGitHubPRClient:
    def __init__(self) -> None:
        self.files_calls = 0
        self.contents_calls = 0

    async def list_pull_request_files(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, object]]:
        self.files_calls += 1
        assert owner == "tomas-lm"
        assert repo == "mes-pr-review-agent"
        assert number == 7
        return [
            {
                "filename": "app/review/service.py",
                "status": "modified",
                "additions": 4,
                "deletions": 1,
                "changes": 5,
                "sha": "file-sha",
                "patch": "@@ -10,1 +10,2 @@\n-old\n+new\n+line",
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
        self.contents_calls += 1
        if path == "CONTRIBUTING.md":
            raise RuntimeError("404 Not Found")
        return {
            "type": "file",
            "path": path,
            "ref": ref,
            "sha": "content-sha",
            "size": 19,
            "content": f"content for {path}",
        }

    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, object]:
        return {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "pytest",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-06-03T10:00:00Z",
                    "completed_at": "2026-06-03T10:01:00Z",
                    "html_url": "https://github.com/example/check",
                }
            ],
        }


def pr_payload() -> dict[str, object]:
    return {
        "action": "opened",
        "repository": {"full_name": "tomas-lm/mes-pr-review-agent"},
        "pull_request": {
            "number": 7,
            "head": {"sha": "head-sha", "ref": "feature/pr-review"},
            "base": {"sha": "base-sha", "ref": "main"},
        },
    }


def test_pr_context_tools_enforce_state_and_return_github_context(tmp_path) -> None:
    async def run_test() -> None:
        prompt_session = DynamicPromptSession(
            run_id="run-123",
            state=ReviewState.RECEIVED,
            runtime_context={"repository": "tomas-lm/mes-pr-review-agent"},
        )
        fake_client = FakeGitHubPRClient()
        pr_context = build_pr_tool_context(
            payload=pr_payload(),
            client=fake_client,
        )
        registry = build_review_tool_registry(
            prompt_session=prompt_session,
            notes_writer=ReviewNotesWriter(notes_dir=tmp_path),
            pull_request_payload=pr_payload(),
            pr_context=pr_context,
        )

        denied = await registry.call("list_changed_files", {})
        assert denied.ok is False
        assert denied.error == "state_not_allowed"

        prompt_session.rewrite_state_layer(
            target_state=ReviewState.TRIAGE,
            state_prompt="Triar escopo.",
            reason="teste",
        )
        prompt_session.rewrite_state_layer(
            target_state=ReviewState.COLLECT_CONTEXT,
            state_prompt="Coletar diff e regras.",
            reason="teste",
        )
        files = await registry.call("list_changed_files", {})
        assert files.ok is True
        assert files.data["files"][0]["filename"] == "app/review/service.py"

        hunks = await registry.call("get_diff_hunks", {"path": "app/review/service.py"})
        assert hunks.ok is True
        assert hunks.data["files"][0]["hunks"][0]["header"].startswith("@@")
        assert fake_client.files_calls == 1

        rules = await registry.call(
            "read_repo_rules",
            {"paths": ["README.md", "CONTRIBUTING.md"]},
        )
        assert rules.ok is True
        assert rules.data["files"][0]["path"] == "README.md"
        assert rules.data["missing"] == ["CONTRIBUTING.md"]

        ci_status = await registry.call("get_ci_status", {})
        assert ci_status.ok is True
        assert ci_status.data["check_runs"][0]["conclusion"] == "success"

        prompt_session.rewrite_state_layer(
            target_state=ReviewState.INVESTIGATE,
            state_prompt="Investigar arquivo especifico.",
            reason="teste",
        )
        file_at_ref = await registry.call(
            "read_file_at_ref",
            {"path": "app/review/service.py", "ref": "head"},
        )
        assert file_at_ref.ok is True
        assert file_at_ref.data["file"]["resolved_ref"] == "head-sha"
        assert file_at_ref.data["file"]["content"] == "content for app/review/service.py"

    anyio.run(run_test)
