from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

GITHUB_API_VERSION = "2026-03-10"


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
        return await self._get_paginated_list(f"/repos/{owner}/{repo}/pulls/{number}/files")

    async def get_file_contents_at_ref(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> dict[str, Any]:
        encoded_path = quote(path, safe="/")
        data = await self._get(
            f"/repos/{owner}/{repo}/contents/{encoded_path}",
            params={"ref": ref},
            accept="application/vnd.github.object+json",
        )
        if isinstance(data, list):
            return {
                "type": "dir",
                "path": path,
                "ref": ref,
                "entries": [
                    {
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                    }
                    for item in data
                    if isinstance(item, dict)
                ],
            }
        if not isinstance(data, dict):
            raise TypeError("GitHub contents endpoint returned an unexpected payload")

        content = data.get("content")
        encoding = data.get("encoding")
        decoded_content = ""
        if isinstance(content, str) and encoding == "base64":
            decoded_content = base64.b64decode(content.replace("\n", "")).decode(
                "utf-8",
                errors="replace",
            )
        elif isinstance(content, str):
            decoded_content = content

        return {
            "type": data.get("type"),
            "path": data.get("path") or path,
            "ref": ref,
            "sha": data.get("sha"),
            "size": data.get("size"),
            "encoding": encoding,
            "content": decoded_content,
        }

    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, Any]:
        data = await self._get(f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
        if not isinstance(data, dict):
            raise TypeError("GitHub check-runs endpoint did not return an object")
        return data

    async def create_check_run(
        self,
        *,
        owner: str,
        repo: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._post(f"/repos/{owner}/{repo}/check-runs", json=body)
        if not isinstance(data, dict):
            raise TypeError("GitHub create check run endpoint did not return an object")
        return data

    async def update_check_run(
        self,
        *,
        owner: str,
        repo: str,
        check_run_id: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._patch(
            f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
            json=body,
        )
        if not isinstance(data, dict):
            raise TypeError("GitHub update check run endpoint did not return an object")
        return data

    async def list_pull_request_reviews(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, Any]]:
        return await self._get_paginated_list(f"/repos/{owner}/{repo}/pulls/{number}/reviews")

    async def create_pull_request_review(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._post(f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=body)
        if not isinstance(data, dict):
            raise TypeError("GitHub create pull request review endpoint did not return an object")
        return data

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.api_base_url}{path}",
                params=params,
                headers={
                    "Accept": accept,
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            response.raise_for_status()
            return response.json()

    async def _post(self, path: str, *, json: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.api_base_url}{path}",
                headers=self._headers(),
                json=json,
            )
            response.raise_for_status()
            return response.json()

    async def _patch(self, path: str, *, json: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(
                f"{self.api_base_url}{path}",
                headers=self._headers(),
                json=json,
            )
            response.raise_for_status()
            return response.json()

    async def _get_paginated_list(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                response = await client.get(
                    f"{self.api_base_url}{path}",
                    params={"per_page": per_page, "page": page},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {self.token}",
                        "X-GitHub-Api-Version": GITHUB_API_VERSION,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise TypeError("GitHub paginated endpoint did not return a list")
                items.extend(item for item in data if isinstance(item, dict))
                if len(data) < per_page or len(items) >= 3000:
                    return items
                page += 1

    def _headers(self, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
