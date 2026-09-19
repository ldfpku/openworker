"""MCP server config — the standard `mcpServers` JSON, layered global + workspace.

Global:    ~/.config/coworker/mcp.json
Workspace: <workspace>/.coworker/mcp.json   (overrides global on name clash,
           but only after the user trusts that workspace — same gate as
           repository `allowed_commands`)

Paste-compatible with Claude Desktop / Cursor / Codex. `${VAR}` refs in command/args/env/
url/headers are resolved at load time via the SecretStore (env + local `.env`). REST edits
target the **global** file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..secrets import SecretStore, state_dir

logger = logging.getLogger(__name__)

_HTTP_TYPES = {"http", "https", "sse", "streamable-http", "streamable_http"}


class MCPConfigError(RuntimeError):
    """An `mcp.json` is there but could not be read or parsed.

    Kept strictly apart from "the file isn't there": an absent file is a legal empty
    config (the first `put_global_server` creates it), while a FAILED read means the
    user's servers are quite possibly still on disk, just unread this once — the file
    is locked by another process, the volume errored, an outside editor left half a
    JSON object behind, the bytes aren't UTF-8.

    Every mutator below is read-modify-write-the-WHOLE-file, so degrading a failed
    read to `{}` would rewrite the file from an empty base and take every server the
    user had with it — silently, irrecoverably, on one transient IO error. Mutators
    therefore let this propagate and write nothing at all.
    """

    def __init__(self, path: Path, cause: BaseException) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"cannot read MCP config {path}: {cause}")


@dataclass
class MCPServerDef:
    name: str
    transport: str  # "stdio" | "http"
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    include_tools: Optional[list[str]] = None
    exclude_tools: Optional[list[str]] = None
    requires_approval: bool = True
    # "oauth" → browser OAuth 2.1 + PKCE with Dynamic Client Registration (mcp/oauth.py).
    # HTTP transport only; tokens live in the SecretStore, never in this file.
    auth: Optional[str] = None


def global_mcp_path() -> Path:
    return state_dir() / "mcp.json"


def _read(path: Path) -> dict[str, Any]:
    """One `mcp.json` as raw JSON.

    Missing (or blank) file → `{}`; anything else that goes wrong → `MCPConfigError`,
    never a silent `{}` — see that exception for why a read failure must not be allowed
    to look like an empty config. A non-object top level counts as unreadable too:
    callers index the result with `.get`, so a stray JSON list used to surface as an
    AttributeError from inside whichever caller happened to reach it first.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        # Locked file, IO error, permission denied, a directory in the way.
        raise MCPConfigError(path, exc) from exc
    except ValueError as exc:  # UnicodeDecodeError: the file is there but isn't UTF-8
        raise MCPConfigError(path, exc) from exc
    if not text.strip():
        # Deliberate narrow carve-out: an empty file holds no servers, so reading it as
        # an empty config cannot lose anything, while refusing to write would wedge the
        # user out of ever adding a server again without hand-deleting the file.
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPConfigError(path, exc) from exc
    if not isinstance(data, dict):
        raise MCPConfigError(
            path, TypeError(f"top level is {type(data).__name__}, not an object")
        )
    return data


def _config_paths(
    workspace: Optional[str | Path], *, workspace_trusted: bool
) -> list[Path]:
    """Config files to merge. Workspace MCP is executable provenance (stdio spawn),
    so an untrusted repo's `.coworker/mcp.json` is never read — cloning alone must
    not be enough to define processes that run at session open.
    """
    paths = [global_mcp_path()]
    if workspace and workspace_trusted:
        paths.append(Path(workspace).expanduser() / ".coworker" / "mcp.json")
    return paths


def _parse(name: str, raw: dict[str, Any], secrets: SecretStore) -> MCPServerDef:
    raw = secrets.resolve(raw)  # resolve ${VAR} everywhere before building the def
    declared = str(raw.get("type", "")).lower()
    is_http = declared in _HTTP_TYPES or bool(raw.get("url"))
    return MCPServerDef(
        name=name,
        transport="http" if is_http else "stdio",
        command=raw.get("command"),
        args=list(raw.get("args", []) or []),
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        cwd=raw.get("cwd"),
        url=raw.get("url"),
        headers={str(k): str(v) for k, v in (raw.get("headers") or {}).items()},
        enabled=bool(raw.get("enabled", True)),
        include_tools=raw.get("include_tools"),
        exclude_tools=raw.get("exclude_tools"),
        requires_approval=bool(raw.get("requires_approval", True)),
        auth=(str(raw["auth"]).lower() if raw.get("auth") else None),
    )


def load_mcp_servers(
    workspace: Optional[str | Path] = None,
    *,
    secrets: Optional[SecretStore] = None,
    workspace_trusted: bool = False,
) -> list[MCPServerDef]:
    """Merge global + (when trusted) workspace `mcpServers` into parsed server defs.

    Only trusted workspaces contribute — the same consent boundary as repository
    ``allowed_commands`` — and **global wins on name clash**, so even a trusted repo
    cannot silently redefine a global server by reusing its name. ``${VAR}`` refs in
    a workspace def are resolved from the user's env, which is acceptable only because
    the workspace is trusted; untrusted workspaces are never read.
    """
    secrets = secrets or SecretStore()
    merged: dict[str, dict[str, Any]] = {}
    for path in _config_paths(workspace, workspace_trusted=workspace_trusted):
        try:
            entries = _read(path).get("mcpServers") or {}
        except MCPConfigError as exc:
            # READ-ONLY path, and it sits on the session-open hot path: an unreadable
            # file degrades to "contributes no servers" rather than failing session
            # creation outright. Logged, never swallowed. The mutators below take the
            # opposite side and refuse to write — that asymmetry is the point: missing
            # servers for one turn is recoverable, an overwritten config is not.
            logger.warning("skipping unreadable MCP config: %s", exc)
            continue
        for name, raw in entries.items():
            if isinstance(raw, dict):
                merged.setdefault(name, raw)  # global first → global wins on clash
    return [_parse(name, raw, secrets) for name, raw in merged.items()]


# -- raw global-file mutation (REST) -------------------------------------------
def read_global() -> dict[str, dict[str, Any]]:
    """Raw `mcpServers` map from the global file (no `${VAR}` resolution).

    No file yet → `{}`. Unreadable or corrupt file → raises `MCPConfigError`: callers
    that merely display the list catch it and degrade, callers that are about to write
    MUST let it through (see that exception's docstring).
    """
    return dict(_read(global_mcp_path()).get("mcpServers") or {})


def _write_global(servers: dict[str, dict[str, Any]]) -> None:
    path = global_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8")
    tmp.replace(path)


def put_global_server(name: str, config: dict[str, Any]) -> None:
    """Add or replace ONE server, leaving the rest of the file as it was.

    `read_global()` raising here is load-bearing and must not be caught: this is the
    read-modify-write-whole-file mutator, so a failed read degraded to `{}` would write
    a file holding only `name` and drop every other server the user had. On
    `MCPConfigError` nothing is written at all and the caller reports the failure.
    """
    servers = read_global()
    servers[name] = config
    _write_global(servers)


def patch_global_server(name: str, changes: dict[str, Any]) -> bool:
    """Merge `changes` into one existing server. `False` = no such server.

    Raises `MCPConfigError` when the file cannot be read: "unreadable" is NOT "absent",
    and answering `False` there would tell the user their server is gone while it sits
    on disk untouched — and the next write-through would then be built on `{}`.
    """
    servers = read_global()
    if name not in servers:
        return False
    servers[name] = {**servers[name], **changes}
    _write_global(servers)
    return True


def delete_global_server(name: str) -> bool:
    """Remove one server. `False` = no such server; `MCPConfigError` = unreadable file.

    A delete rewrites the whole file too, so an unreadable file has to stop it: the
    servers that stay can only be preserved if they were read in the first place.
    """
    servers = read_global()
    if name not in servers:
        return False
    del servers[name]
    _write_global(servers)
    return True
