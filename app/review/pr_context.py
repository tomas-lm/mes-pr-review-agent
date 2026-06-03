from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_RULE_PATHS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
)

MAX_LISTED_FILES = 100
MAX_PATCH_CHARS = 12_000
MAX_FILE_CHARS = 30_000
MAX_RULE_CHARS = 12_000


class GitHubPRClient(Protocol):
    async def list_pull_request_files(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> list[dict[str, Any]]: ...

    async def get_file_contents_at_ref(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        ref: str,
    ) -> dict[str, Any]: ...

    async def list_check_runs_for_ref(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, Any]: ...


@dataclass
class PullRequestToolContext:
    owner: str
    repo: str
    number: int
    client: GitHubPRClient | None
    head_sha: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    base_ref: str | None = None
    unavailable_reason: str | None = None
    _changed_files: list[dict[str, Any]] | None = None
    _files_by_ref: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    _ci_status: dict[str, Any] | None = None

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    async def list_changed_files(
        self,
        *,
        max_files: int = MAX_LISTED_FILES,
    ) -> tuple[list[dict[str, Any]], bool]:
        self._ensure_available()
        if self._changed_files is None:
            assert self.client is not None
            self._changed_files = await self.client.list_pull_request_files(
                owner=self.owner,
                repo=self.repo,
                number=self.number,
            )
        normalized = [_normalize_changed_file(item) for item in self._changed_files]
        return normalized[:max_files], len(normalized) > max_files

    async def get_diff_hunks(
        self,
        *,
        path: str | None = None,
        max_files: int = 20,
        max_patch_chars: int = MAX_PATCH_CHARS,
    ) -> tuple[list[dict[str, Any]], bool]:
        self._ensure_available()
        if self._changed_files is None:
            assert self.client is not None
            self._changed_files = await self.client.list_pull_request_files(
                owner=self.owner,
                repo=self.repo,
                number=self.number,
            )
        selected: list[dict[str, Any]] = []
        for item in self._changed_files:
            filename = item.get("filename")
            if not isinstance(filename, str):
                continue
            if path and filename != path:
                continue
            patch = item.get("patch")
            selected.append(
                {
                    "filename": filename,
                    "status": item.get("status"),
                    "previous_filename": item.get("previous_filename"),
                    "hunks": _extract_hunks(str(patch), max_patch_chars=max_patch_chars)
                    if isinstance(patch, str)
                    else [],
                    "has_patch": isinstance(patch, str),
                    "patch_truncated": isinstance(patch, str) and len(patch) > max_patch_chars,
                }
            )
            if len(selected) >= max_files:
                break
        if path and not selected:
            raise ValueError(f"path is not present in this pull request diff: {path}")
        total_matching = (
            sum(1 for item in self._changed_files if item.get("filename") == path)
            if path
            else len(self._changed_files)
        )
        return selected, total_matching > len(selected)

    async def read_file_at_ref(
        self,
        *,
        path: str,
        ref: str,
        max_chars: int = MAX_FILE_CHARS,
    ) -> tuple[dict[str, Any], bool]:
        self._ensure_available()
        _validate_repo_path(path)
        resolved_ref = self.resolve_ref(ref)
        cache_key = (resolved_ref, path)
        if cache_key not in self._files_by_ref:
            assert self.client is not None
            self._files_by_ref[cache_key] = await self.client.get_file_contents_at_ref(
                owner=self.owner,
                repo=self.repo,
                path=path,
                ref=resolved_ref,
            )
        data = dict(self._files_by_ref[cache_key])
        content = data.get("content")
        truncated = False
        if isinstance(content, str) and len(content) > max_chars:
            data["content"] = content[:max_chars]
            truncated = True
        data["requested_ref"] = ref
        data["resolved_ref"] = resolved_ref
        return data, truncated

    async def read_repo_rules(
        self,
        *,
        paths: list[str] | None = None,
        ref: str = "base",
    ) -> dict[str, Any]:
        selected_paths = paths or list(DEFAULT_RULE_PATHS)
        files: list[dict[str, Any]] = []
        missing: list[str] = []
        errors: list[dict[str, str]] = []
        for path in selected_paths:
            try:
                data, truncated = await self.read_file_at_ref(
                    path=path,
                    ref=ref,
                    max_chars=MAX_RULE_CHARS,
                )
            except FileNotFoundError:
                missing.append(path)
            except Exception as exc:  # noqa: BLE001 - GitHub 404 and API errors become tool data
                message = str(exc)
                if "404" in message or "Not Found" in message:
                    missing.append(path)
                else:
                    errors.append({"path": path, "error": message})
            else:
                files.append(
                    {
                        "path": data.get("path") or path,
                        "ref": data.get("resolved_ref"),
                        "size": data.get("size"),
                        "content": data.get("content"),
                        "truncated": truncated,
                    }
                )
        return {"files": files, "missing": missing, "errors": errors}

    async def get_ci_status(self) -> dict[str, Any]:
        self._ensure_available()
        ref = self.head_sha or self.head_ref
        if not ref:
            raise ValueError("head SHA/ref is not available")
        if self._ci_status is None:
            assert self.client is not None
            self._ci_status = await self.client.list_check_runs_for_ref(
                owner=self.owner,
                repo=self.repo,
                ref=ref,
            )
        check_runs = self._ci_status.get("check_runs")
        normalized = (
            [
                {
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "conclusion": item.get("conclusion"),
                    "started_at": item.get("started_at"),
                    "completed_at": item.get("completed_at"),
                    "html_url": item.get("html_url"),
                }
                for item in check_runs
                if isinstance(item, dict)
            ]
            if isinstance(check_runs, list)
            else []
        )
        return {
            "ref": ref,
            "total_count": self._ci_status.get("total_count"),
            "check_runs": normalized,
        }

    def resolve_ref(self, ref: str) -> str:
        normalized = ref.strip()
        if normalized in {"head", "HEAD", "right", "RIGHT"}:
            if not (self.head_sha or self.head_ref):
                raise ValueError("head ref is not available")
            return str(self.head_sha or self.head_ref)
        if normalized in {"base", "BASE", "left", "LEFT"}:
            if not (self.base_sha or self.base_ref):
                raise ValueError("base ref is not available")
            return str(self.base_sha or self.base_ref)
        if not normalized:
            raise ValueError("ref is required")
        return normalized

    def _ensure_available(self) -> None:
        if self.client is None:
            raise RuntimeError(
                self.unavailable_reason or "GitHub client is unavailable for this review run"
            )


def build_pr_tool_context(
    *,
    payload: dict[str, Any],
    client: GitHubPRClient | None,
    unavailable_reason: str | None = None,
) -> PullRequestToolContext:
    repository = payload.get("repository") if isinstance(payload, dict) else {}
    pull_request = payload.get("pull_request") if isinstance(payload, dict) else {}
    full_name = repository.get("full_name") if isinstance(repository, dict) else None
    if not isinstance(full_name, str) or "/" not in full_name:
        raise ValueError("repository.full_name is required")
    owner, repo = full_name.split("/", 1)
    number = pull_request.get("number") if isinstance(pull_request, dict) else None
    if not isinstance(number, int):
        raise ValueError("pull_request.number is required")
    head = pull_request.get("head") if isinstance(pull_request, dict) else {}
    base = pull_request.get("base") if isinstance(pull_request, dict) else {}
    return PullRequestToolContext(
        owner=owner,
        repo=repo,
        number=number,
        client=client,
        head_sha=head.get("sha") if isinstance(head, dict) else None,
        base_sha=base.get("sha") if isinstance(base, dict) else None,
        head_ref=head.get("ref") if isinstance(head, dict) else None,
        base_ref=base.get("ref") if isinstance(base, dict) else None,
        unavailable_reason=unavailable_reason,
    )


def _normalize_changed_file(item: dict[str, Any]) -> dict[str, Any]:
    patch = item.get("patch")
    return {
        "filename": item.get("filename"),
        "status": item.get("status"),
        "additions": item.get("additions"),
        "deletions": item.get("deletions"),
        "changes": item.get("changes"),
        "previous_filename": item.get("previous_filename"),
        "sha": item.get("sha"),
        "blob_url": item.get("blob_url"),
        "raw_url": item.get("raw_url"),
        "has_patch": isinstance(patch, str),
        "patch_chars": len(patch) if isinstance(patch, str) else 0,
    }


def _extract_hunks(patch: str, *, max_patch_chars: int) -> list[dict[str, str]]:
    if not patch:
        return []
    hunks: list[dict[str, str]] = []
    current_header = ""
    current_lines: list[str] = []
    used_chars = 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            if current_header:
                body = "\n".join(current_lines)
                hunks.append({"header": current_header, "patch": body})
                used_chars += len(body)
                if used_chars >= max_patch_chars:
                    return hunks
            current_header = line
            current_lines = [line]
            continue
        if (
            current_header
            and used_chars + sum(len(item) for item in current_lines) < max_patch_chars
        ):
            current_lines.append(line)
    if current_header:
        body = "\n".join(current_lines)
        if len(body) > max_patch_chars:
            body = body[:max_patch_chars]
        hunks.append({"header": current_header, "patch": body})
    return hunks


def _validate_repo_path(path: str) -> None:
    if not path.strip():
        raise ValueError("path is required")
    if path.startswith("/") or "\\" in path:
        raise ValueError("path must be repository-relative")
    if any(part == ".." for part in path.split("/")):
        raise ValueError("path cannot contain '..'")
