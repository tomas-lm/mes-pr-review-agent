from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.github.webhooks import expected_signature
from app.main import create_app
from app.storage.runs import RunStore


def make_client() -> tuple[TestClient, RunStore]:
    store = RunStore()
    app = create_app(
        settings=Settings(GITHUB_WEBHOOK_SECRET="test-secret"),
        run_store=store,
    )
    return TestClient(app), store


def signed_headers(payload: dict[str, Any], *, delivery_id: str = "delivery-1") -> dict[str, str]:
    body = json.dumps(payload).encode("utf-8")
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": expected_signature(body, "test-secret"),
    }


def pr_payload(action: str = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": 123},
        "repository": {"full_name": "tomas-lm/mes-pr-review-agent"},
        "pull_request": {
            "number": 7,
            "head": {"sha": "abc123"},
        },
    }


def test_health() -> None:
    client, _ = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_rejects_invalid_signature() -> None:
    client, _ = make_client()
    payload = pr_payload()

    response = client.post(
        "/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )

    assert response.status_code == 403


def test_pull_request_opened_creates_received_run() -> None:
    client, store = make_client()
    payload = pr_payload()

    response = client.post(
        "/webhooks/github",
        content=json.dumps(payload).encode("utf-8"),
        headers=signed_headers(payload),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["state"] == "RECEIVED"
    assert body["run_id"]

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].repository == "tomas-lm/mes-pr-review-agent"
    assert runs[0].pull_request_number == 7
    assert runs[0].head_sha == "abc123"
    assert runs[0].installation_id == 123


def test_duplicate_delivery_does_not_create_second_run() -> None:
    client, store = make_client()
    payload = pr_payload()
    headers = signed_headers(payload)

    first = client.post(
        "/webhooks/github",
        content=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    second = client.post(
        "/webhooks/github",
        content=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert len(store.list_runs()) == 1


def test_unsupported_action_is_ignored() -> None:
    client, store = make_client()
    payload = pr_payload(action="closed")

    response = client.post(
        "/webhooks/github",
        content=json.dumps(payload).encode("utf-8"),
        headers=signed_headers(payload),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert len(store.list_runs()) == 0
