"""Facts the engine computes for the Auto-Approve reviewer (OPE-235).

Models are unreliable at checks that code gets right: whether `github.com.evil.example`
is GitHub, whether a file has uncommitted changes, whether a file name looks like a
credential. The engine works these out from the session record and the action, and the
reviewer gets them as short lines from a FIXED vocabulary: no host names, paths or any
other text the agent controls ever travels in a fact, so the reviewer's
never-read-untrusted-content rule holds.

Every fact fails toward "could not be determined", never toward a reassuring value, and
none of them is a permission: a destination the user named can still be misused.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .risk import RiskClass, classify
from .workspace_safety import (
    IGNORED,
    TRACKED_CLEAN,
    TRACKED_MODIFIED,
    UNTRACKED,
    git_file_state,
    has_secret_value,
    is_sensitive_name,
)

EXTERNAL_READ = "content from outside (web, email, connectors, downloads) was read earlier in this session"
DESTINATION_NAMED = "destination: named in the user's own messages"
DESTINATION_NOT_NAMED = "destination: not named in the user's own messages"
DESTINATION_UNKNOWN = "destination: could not be determined from the action"
SECRET_INVOLVED = "a secret-looking file name or value is involved"
_FILE_STATE_LINES = {
    "new": "target file: new",
    TRACKED_CLEAN: "target file: unchanged in git",
    TRACKED_MODIFIED: "target file: has uncommitted changes",
    UNTRACKED: "target file: not tracked by git",
    IGNORED: "target file: ignored by git",
    "unknown": "target file: state unknown",
}
# Worst first: the line reports the least recoverable target of a multi-file write.
_FILE_STATE_ORDER = [TRACKED_MODIFIED, UNTRACKED, IGNORED, "unknown", TRACKED_CLEAN, "new"]

# Programs that reach the network from a shell command line (bash and PowerShell names).
_NETWORK_CLIENTS = {
    "curl", "curl.exe", "wget", "wget.exe", "http", "https", "httpie", "nc", "ncat",
    "netcat", "telnet", "ftp", "sftp", "scp", "ssh", "rsync",
    "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "start-bitstransfer",
}
_URL_HOST = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s'\"`<>:?#\\]+)", re.IGNORECASE)
_DOMAIN = re.compile(r"(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})(?![\w-])", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOWNLOAD_TOOLS = {"github_clone", "github_pull", "email_download_attachment"}
_PATH_ARGS = ("path", "file", "files", "filename", "attachment", "attachments", "source", "src")


def _words(command: str) -> list[str]:
    return [w.strip("'\"`()[]{};|&") for w in re.split(r"\s+", command or "") if w]


def shell_reaches_network(command: str) -> bool:
    """A command line that names a network client or a URL."""
    words = [w.lower() for w in _words(command)]
    names = {Path(w).name for w in words}
    return bool(names & _NETWORK_CLIENTS) or bool(_URL_HOST.search(command or ""))


def is_external_read(tool_name: str, arguments: dict[str, Any], metadata: Any = None) -> bool:
    """Whether a SUCCESSFUL call brought outside content into the agent's context."""
    if classify(tool_name, metadata) is RiskClass.EGRESS:
        return True  # web_fetch, web_search, browser_open_url, enrichment lookups
    if tool_name.startswith("browser_") or tool_name in _DOWNLOAD_TOOLS:
        return True
    if getattr(metadata, "category", "") == "mcp" or tool_name.startswith("mcp__"):
        return True
    try:
        from .connectors.tool_defs import _KIND_BY_NAME
    except ImportError:  # pragma: no cover - connectors always ship
        _KIND_BY_NAME = {}
    if _KIND_BY_NAME.get(tool_name) == "read":
        return True
    if tool_name == "run_shell":
        return shell_reaches_network(str((arguments or {}).get("command", "")))
    return False


def _named(user_texts: Iterable[str]) -> tuple[set[str], str]:
    """Hosts/domains and the lowercased text the user wrote."""
    text = "\n".join(t for t in user_texts if t).lower()
    domains = {m.group(1).lower() for m in _URL_HOST.finditer(text)}
    domains |= {m.group(1).lower() for m in _DOMAIN.finditer(text)}
    domains |= {e.split("@", 1)[1] for e in _EMAIL.findall(text)}
    return {d.strip(".") for d in domains if d}, text


def _host_named(host: str, domains: set[str]) -> bool:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in domains)


def _target_named(target: str, text: str) -> bool:
    target = target.strip().lower()
    if len(target) < 3:
        return False
    return re.search(r"(?<![\w@.-])" + re.escape(target) + r"(?![\w-])", text) is not None


def destination_fact(
    tool_name: str,
    arguments: dict[str, Any],
    user_texts: Iterable[str],
    *,
    metadata: Any = None,
    egress_host: Optional[Callable[[str, dict[str, Any]], str]] = None,
) -> str:
    """One of the DESTINATION_* lines, or "" when the action sends nothing out."""
    risk = classify(tool_name, metadata)
    domains, text = _named(user_texts)
    if risk is RiskClass.EGRESS:
        host = egress_host(tool_name, arguments) if egress_host else ""
        if not host:
            return DESTINATION_UNKNOWN
        return DESTINATION_NAMED if _host_named(host, domains) else DESTINATION_NOT_NAMED
    if risk is RiskClass.EXTERNAL:
        try:
            from .connectors.tool_defs import target_arg_for
        except ImportError:  # pragma: no cover
            return DESTINATION_UNKNOWN
        arg = target_arg_for(tool_name)
        target = str((arguments or {}).get(arg) or "").strip() if arg else ""
        if not target:
            return DESTINATION_UNKNOWN
        if _target_named(target, text):
            return DESTINATION_NAMED  # the exact recipient, channel or repo appears
        if "@" not in target and "." in target and _host_named(target, domains):
            return DESTINATION_NAMED  # a domain-like target under a domain the user named
        # An email address counts only when that exact address appears: naming a company
        # domain does not name every mailbox in it.
        return DESTINATION_NOT_NAMED
    if tool_name == "run_shell":
        command = str((arguments or {}).get("command", ""))
        if not shell_reaches_network(command):
            return ""
        hosts = [m.group(1) for m in _URL_HOST.finditer(command)]
        if not hosts:
            return DESTINATION_UNKNOWN
        return DESTINATION_NAMED if all(_host_named(h, domains) for h in hosts) else DESTINATION_NOT_NAMED
    return ""


def file_state_fact(targets: list[Path]) -> str:
    """The TARGET line for a write's resolved targets, or "" for no targets."""
    if not targets:
        return ""
    states = []
    for target in targets:
        states.append("new" if not target.exists() else git_file_state(target))
    worst = min(states, key=lambda s: _FILE_STATE_ORDER.index(s) if s in _FILE_STATE_ORDER else 0)
    return _FILE_STATE_LINES.get(worst, _FILE_STATE_LINES["unknown"])


def referenced_names(tool_name: str, arguments: dict[str, Any], write_targets: list[Path]) -> list[str]:
    names = [t.name for t in write_targets]
    args = arguments or {}
    for key in _PATH_ARGS:
        value = args.get(key)
        values = value if isinstance(value, (list, tuple)) else [value]
        names += [Path(str(v).replace("\\", "/")).name for v in values if isinstance(v, str) and v]
    if tool_name == "run_shell":
        for word in _words(str(args.get("command", ""))):
            word = word.lstrip("@")  # curl -F file=@.env / --data-binary @id_rsa
            if "=" in word:
                word = word.rsplit("=", 1)[-1].lstrip("@")
            names.append(Path(word.replace("\\", "/")).name)
    return [n for n in names if n]


def secret_fact(tool_name: str, arguments: dict[str, Any], write_targets: list[Path]) -> str:
    if has_secret_value(arguments or {}):
        return SECRET_INVOLVED
    if any(is_sensitive_name(n) for n in referenced_names(tool_name, arguments, write_targets)):
        return SECRET_INVOLVED
    return ""


def compute_facts(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    user_texts: Iterable[str],
    external_read: bool,
    write_targets: list[Path],
    metadata: Any = None,
    egress_host: Optional[Callable[[str, dict[str, Any]], str]] = None,
) -> list[str]:
    """Every applicable fact line, in a stable order."""
    facts = []
    if external_read:
        facts.append(EXTERNAL_READ)
    destination = destination_fact(
        tool_name, arguments, list(user_texts), metadata=metadata, egress_host=egress_host
    )
    if destination:
        facts.append(destination)
    state = file_state_fact(write_targets)
    if state:
        facts.append(state)
    secret = secret_fact(tool_name, arguments, write_targets)
    if secret:
        facts.append(secret)
    return facts
