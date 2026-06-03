from __future__ import annotations

import time
from typing import Any

import httpx
import jwt


def normalize_private_key(private_key: str) -> str:
    return private_key.replace("\\n", "\n").strip()


def generate_app_jwt(*, app_id: str, private_key: str, now: int | None = None) -> str:
    issued_at = int(now if now is not None else time.time()) - 60
    expires_at = issued_at + 600
    payload = {"iat": issued_at, "exp": expires_at, "iss": app_id}
    return jwt.encode(payload, normalize_private_key(private_key), algorithm="RS256")


class GitHubAppAuth:
    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.api_base_url = api_base_url.rstrip("/")

    async def create_installation_token(
        self,
        *,
        installation_id: int,
        repositories: list[str] | None = None,
        permissions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = generate_app_jwt(app_id=self.app_id, private_key=self.private_key)
        body: dict[str, Any] = {}
        if repositories:
            body["repositories"] = repositories
        if permissions:
            body["permissions"] = permissions

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.api_base_url}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=body,
            )
            response.raise_for_status()
            return response.json()
