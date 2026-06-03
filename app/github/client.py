from __future__ import annotations

from typing import Any

import httpx


class GitHubClient:
    def __init__(self, *, token: str, api_base_url: str = "https://api.github.com") -> None:
        self.token = token
        self.api_base_url = api_base_url.rstrip("/")

    async def get_pull_request(self, *, owner: str, repo: str, number: int) -> dict[str, Any]:
        return await self._get(f"/repos/{owner}/{repo}/pulls/{number}")

    async def list_pull_request_files(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, Any]]:
        data = await self._get(f"/repos/{owner}/{repo}/pulls/{number}/files")
        if not isinstance(data, list):
            raise TypeError("GitHub files endpoint did not return a list")
        return data

    async def _get(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.api_base_url}{path}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return response.json()
