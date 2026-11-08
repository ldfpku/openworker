"""A small GitHub client for skill update checks (来源与升级 §6, §8).

Two calls only: a tree listing (``api.github.com``, counted against the hourly quota — 60
without a token, 5,000 with one) and a raw file download (``raw.githubusercontent.com``,
not counted). A token is read from ``GITHUB_TOKEN`` / ``GH_TOKEN`` and sent as a header;
it never appears in a log line, an error message, or a return value.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

import httpx

from ..proxy_env import normalize_no_proxy

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_OR_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class GitHubError(Exception):
    """A failed call. `kind`: rate_limited / not_found / http / network / too_large.
    The message is written for the person and never carries the token."""

    def __init__(self, kind: str, message: str, reset_at: Optional[float] = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.reset_at = reset_at


def _token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def _check_repo(repo: str) -> str:
    if not _REPO_RE.match(repo or "") or ".." in repo:
        raise GitHubError("http", f"不是合法的 GitHub 仓库名：{repo!r}")
    return repo


def _check_ref(ref: str) -> str:
    if not _SHA_OR_REF_RE.match(ref or "") or ".." in ref:
        raise GitHubError("http", f"不是合法的版本标识：{ref!r}")
    return ref


class GitHubClient:
    def __init__(
        self,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        normalize_no_proxy()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "openworker-skill-updates",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        secret = _token() if token is None else token
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        self.authenticated = bool(secret)
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            trust_env=transport is None,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _raise_for(self, resp: httpx.Response, what: str) -> None:
        if resp.status_code < 400:
            return
        remaining = resp.headers.get("x-ratelimit-remaining")
        if resp.status_code in (403, 429) and (remaining == "0" or resp.status_code == 429):
            reset: Optional[float] = None
            try:
                reset = float(resp.headers.get("x-ratelimit-reset") or "")
            except ValueError:
                retry = resp.headers.get("retry-after")
                reset = time.time() + float(retry) if retry and retry.isdigit() else None
            when = time.strftime("%H:%M", time.localtime(reset)) if reset else "稍后"
            hint = "" if self.authenticated else "设置环境变量 GITHUB_TOKEN 可以提高额度。"
            raise GitHubError(
                "rate_limited", f"GitHub 接口额度用完了，{when} 恢复。{hint}", reset
            )
        if resp.status_code == 404:
            raise GitHubError("not_found", f"GitHub 上找不到{what}（仓库可能已删除或是私有的）。")
        raise GitHubError("http", f"GitHub 返回 {resp.status_code}（{what}）。")

    def tree(self, repo: str, ref: str, *, recursive: bool = True) -> dict[str, Any]:
        """``GET /repos/{repo}/git/trees/{ref}`` — `ref` may be a branch, HEAD, or a tree
        SHA (which is what lets us list a locked version)."""
        url = f"{API}/repos/{_check_repo(repo)}/git/trees/{_check_ref(ref)}"
        try:
            resp = self._client.get(url, params={"recursive": "1"} if recursive else None)
        except httpx.HTTPError as exc:
            raise GitHubError("network", f"连不上 GitHub：{type(exc).__name__}") from None
        self._raise_for(resp, f" {repo} 的目录")
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
            raise GitHubError("http", f"GitHub 返回的目录格式不对（{repo}）。")
        return data

    def raw(self, repo: str, ref: str, path: str, *, max_bytes: int) -> bytes:
        """One file's bytes, refused past `max_bytes` without reading the rest."""
        url = f"{RAW}/{_check_repo(repo)}/{_check_ref(ref)}/{path}"
        try:
            with self._client.stream("GET", url) as resp:
                self._raise_for(resp, f"文件 {path}")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise GitHubError("too_large", f"文件 {path} 超过大小上限。")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise GitHubError("network", f"下载 {path} 失败：{type(exc).__name__}") from None
        return b"".join(chunks)
