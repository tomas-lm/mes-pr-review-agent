from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.github.webhooks import WebhookSignatureError, verify_webhook_signature
from app.review.service import ReviewAgentService
from app.storage.runs import RunStore

SUPPORTED_PULL_REQUEST_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


class HealthPayload(BaseModel):
    status: str


class WebhookResult(BaseModel):
    status: str
    delivery_id: str | None = None
    run_id: str | None = None
    state: str | None = None
    reason: str | None = None
    notes_path: str | None = None


def create_app(
    *,
    settings: Settings | None = None,
    run_store: RunStore | None = None,
    review_service: ReviewAgentService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_store = run_store or RunStore()
    resolved_review_service = review_service or ReviewAgentService(settings=resolved_settings)

    app = FastAPI(title="MES PR Review Agent")
    app.state.settings = resolved_settings
    app.state.run_store = resolved_store
    app.state.review_service = resolved_review_service

    @app.get("/health", response_model=HealthPayload)
    async def health() -> HealthPayload:
        return HealthPayload(status="ok")

    @app.post("/webhooks/github", response_model=WebhookResult)
    async def github_webhook(request: Request) -> WebhookResult:
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        event = request.headers.get("X-GitHub-Event")

        if not delivery_id:
            raise HTTPException(status_code=400, detail="missing X-GitHub-Delivery header")
        if not event:
            raise HTTPException(status_code=400, detail="missing X-GitHub-Event header")

        try:
            verify_webhook_signature(
                payload_body=body,
                secret=resolved_settings.github_webhook_secret,
                signature_header=signature,
            )
        except WebhookSignatureError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if resolved_store.has_delivery(delivery_id):
            existing = resolved_store.get_by_delivery(delivery_id)
            return WebhookResult(
                status="duplicate",
                delivery_id=delivery_id,
                run_id=existing.run_id if existing else None,
                state=existing.state.value if existing else None,
            )

        payload = await request.json()
        if event != "pull_request":
            return WebhookResult(
                status="ignored", delivery_id=delivery_id, reason="unsupported event"
            )

        action = str(payload.get("action") or "")
        if action not in SUPPORTED_PULL_REQUEST_ACTIONS:
            return WebhookResult(
                status="ignored",
                delivery_id=delivery_id,
                reason=f"unsupported pull_request action: {action}",
            )

        run = resolved_store.create_pull_request_run(
            delivery_id=delivery_id,
            event=event,
            action=action,
            repository=_repository_full_name(payload),
            pull_request_number=_pull_request_number(payload),
            head_sha=_head_sha(payload),
            installation_id=_installation_id(payload),
        )
        review_result = await resolved_review_service.run_for_pull_request(
            run=run,
            payload=payload,
        )
        return WebhookResult(
            status=review_result.status,
            delivery_id=delivery_id,
            run_id=run.run_id,
            state=run.state.value,
            reason=review_result.error,
            notes_path=review_result.notes_path,
        )

    return app


def _repository_full_name(payload: dict[str, Any]) -> str:
    repository = payload.get("repository")
    if not isinstance(repository, dict) or not repository.get("full_name"):
        raise HTTPException(status_code=400, detail="missing repository.full_name")
    return str(repository["full_name"])


def _pull_request_number(payload: dict[str, Any]) -> int:
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict) or pull_request.get("number") is None:
        raise HTTPException(status_code=400, detail="missing pull_request.number")
    return int(pull_request["number"])


def _head_sha(payload: dict[str, Any]) -> str:
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        raise HTTPException(status_code=400, detail="missing pull_request")
    head = pull_request.get("head")
    if not isinstance(head, dict) or not head.get("sha"):
        raise HTTPException(status_code=400, detail="missing pull_request.head.sha")
    return str(head["sha"])


def _installation_id(payload: dict[str, Any]) -> int:
    installation = payload.get("installation")
    if not isinstance(installation, dict) or installation.get("id") is None:
        raise HTTPException(status_code=400, detail="missing installation.id")
    return int(installation["id"])


app = create_app()
