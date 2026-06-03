from __future__ import annotations

import anyio

from app.config import Settings
from app.review.service import ReviewAgentService
from app.state_machine.states import ReviewState
from app.storage.runs import ReviewRun


class FakeModelClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.system_prompts: list[str] = []

    async def complete(self, *, messages: list[dict[str, str]], system_prompt: str) -> str:
        self.system_prompts.append(system_prompt)
        if not self.responses:
            raise RuntimeError("no fake responses left")
        return self.responses.pop(0)


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


def pr_payload() -> dict[str, object]:
    return {
        "action": "opened",
        "installation": {"id": 123},
        "repository": {"full_name": "tomas-lm/mes-pr-review-agent", "private": False},
        "sender": {"login": "tomas-lm"},
        "pull_request": {
            "number": 7,
            "title": "Fix email normalization",
            "body": "This PR updates email normalization.",
            "draft": False,
            "head": {"sha": "abc123", "ref": "feature/email"},
            "base": {"ref": "main"},
        },
    }


def test_review_service_runs_agentic_loop_and_updates_prompt_state(tmp_path) -> None:
    async def run_test() -> None:
        fake_model = FakeModelClient(
            [
                '<tool name="get_state_machine">{}</tool>',
                (
                    '<tool name="rewrite_state_prompt">'
                    '{"state":"TRIAGE","state_prompt":"Verificar escopo e risco do PR.",'
                    '"reason":"Iniciar triagem do PR recebido."}'
                    "</tool>"
                ),
                (
                    '<tool name="append_review_observation">'
                    '{"category":"triage","message":"PR pequeno e elegivel para analise.",'
                    '"todo":"Coletar diff e arquivos alterados.","evidence":["PR nao e draft"]}'
                    "</tool>"
                ),
                (
                    "<final>"
                    '{"decision":"comment","summary":"Triagem inicial concluida.",'
                    '"findings":[],"trace_notes":["Estado TRIAGE registrado."]}'
                    "</final>"
                ),
            ]
        )
        service = ReviewAgentService(
            settings=Settings(GITHUB_WEBHOOK_SECRET="test-secret"),
            model_client=fake_model,
            notes_dir=tmp_path,
        )
        run = make_run()

        result = await service.run_for_pull_request(run=run, payload=pr_payload())

        assert result.status == "completed"
        assert result.final_payload == {
            "decision": "approve",
            "publishable_findings": [],
            "summary_findings": [],
            "discarded_findings": [],
            "check_conclusion": "success",
            "review_event": "APPROVE",
        }
        assert run.state == ReviewState.TRIAGE
        assert len(fake_model.system_prompts) == 4
        assert "Estado atual: RECEIVED" in fake_model.system_prompts[0]
        assert "Estado atual: TRIAGE" in fake_model.system_prompts[-1]
        notes = (tmp_path / "run-123.md").read_text(encoding="utf-8")
        assert "PR pequeno e elegivel para analise." in notes
        assert "Coletar diff e arquivos alterados." in notes
        assert "Validador processou a resposta final do agente" in notes

    anyio.run(run_test)


def test_review_service_records_missing_llm_key_as_needs_human(tmp_path) -> None:
    async def run_test() -> None:
        service = ReviewAgentService(
            settings=Settings(GITHUB_WEBHOOK_SECRET="test-secret"),
            notes_dir=tmp_path,
        )
        run = make_run()

        result = await service.run_for_pull_request(run=run, payload=pr_payload())

        assert result.status == "needs_human"
        assert run.state == ReviewState.NEEDS_HUMAN
        notes = (tmp_path / "run-123.md").read_text(encoding="utf-8")
        assert "LLM_API_KEY ausente" in notes

    anyio.run(run_test)


def test_review_service_returns_error_for_invalid_final_json(tmp_path) -> None:
    async def run_test() -> None:
        service = ReviewAgentService(
            settings=Settings(GITHUB_WEBHOOK_SECRET="test-secret"),
            model_client=FakeModelClient(["<final>{bad json}</final>"]),
            notes_dir=tmp_path,
        )
        run = make_run()

        result = await service.run_for_pull_request(run=run, payload=pr_payload())

        assert result.status == "error"
        assert result.error is not None
        assert "final answer is not valid JSON" in result.error
        assert run.state == ReviewState.ERROR

    anyio.run(run_test)
