"""Configuration — layered TOML: built-in defaults < global < per-workspace.

Global:    <state-dir>/config.toml   (see `secrets.state_dir`; platform-native)
Workspace: <workspace>/.coworker/config.toml   (overrides global)

Workspace command allowances apply only after the user trusts that exact canonical
workspace path. Other permission grants remain global-only.
"""

from __future__ import annotations

import os

try:
    import tomllib  # stdlib since 3.11
except ModuleNotFoundError:  # 3.10, the floor requires-python declares
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .secrets import state_dir

# Commands auto-run WITHOUT an approval prompt. There is no generally safe executable:
# nominally read-only programs can read secrets outside the workspace, expand environment
# variables, load project-controlled config/plugins, or execute helpers (for example
# `find -exec` and pytest collection). Keep the built-in list empty. A user may explicitly
# opt into command prefixes in their user-owned global config, accepting that authority.
DEFAULT_ALLOWED_COMMANDS: list[str] = []


@dataclass
class Config:
    model: str = "gpt-5.6-sol"
    mode: str = "interactive"
    max_iterations: int = 150
    # Companion gate to max_iterations, in the unit the bill uses. Counting ROUNDS
    # cannot distinguish a turn that read four small files from one that read four
    # 40k-line logs, so the round gate stops both at the same place. 0 = off, which
    # is the default: a ceiling that fires on legitimate long work is worse than none,
    # and the right number is workload-specific (set it per workspace in config.toml).
    max_turn_tokens: int = 0
    # OPE-186 change 3: cap on the auto-compaction trigger, in tokens. The engine compacts
    # at min(80% of the model's window, this cap); the built-in cap is 250,000, which on a
    # 1M-window model fired once in 445 long sessions. Lower it (e.g. 60000) to
    # summarise long sessions earlier. Environment override: COWORKER_COMPACTION_CAP_TOKENS.
    # In this fork the Settings pref (manager.compaction_settings) overrides this default.
    compaction_cap_tokens: Optional[int] = None
    # OPE-189: output ceiling for the summariser call, in tokens. Unset = 16,000. On a
    # reasoning model the budget is shared with the model's thinking, so a low value means
    # the summary itself never gets written. Environment override:
    # COWORKER_COMPACTION_SUMMARY_MAX_TOKENS.
    compaction_summary_max_tokens: Optional[int] = None
    allowed_commands: list[str] = field(
        default_factory=lambda: list(DEFAULT_ALLOWED_COMMANDS)
    )
    # In "custom" permission mode, these tools are auto-approved (e.g. file edits)
    # while everything else still asks.
    auto_allow: list[str] = field(default_factory=list)
    # Egress destinations `web_fetch` may reach WITHOUT an approval prompt (exact host or
    # subdomain). Empty by default — the first fetch to any host asks. A power-user opt-in,
    # like `allowed_commands`; user-global only, so a repo can't widen the agent's network reach.
    allowed_domains: list[str] = field(default_factory=list)
    # Auto-Approve mode's feature flag (spec §1.5): when true, sessions get an LLM reviewer
    # that judges would-be approval cards in Mode.AUTO_APPROVE. User-global only — a cloned
    # repo must not be able to hand itself a looser reviewer.
    #
    # On by default since 0.7.4 (owner decision 2026-10-13): with it off, the mode picker
    # simply had no 自动审批 row, and users who had never found the Settings switch reported
    # the option as missing. The flag only OFFERS the mode — nothing is reviewed, and no
    # extra model call is made, until a user picks it for a session. An explicit choice
    # still wins: the Settings toggle (prefs) or `auto_approve = false` in config.toml.
    auto_approve: bool = True
    # Shadow evaluation (spec Part 6 step 3): the reviewer records what it WOULD have
    # decided on every approval card while the human still decides. Verdicts land in the
    # audit log next to the human's outcome and nothing else changes — this is how the ship
    # gates (zero false-allows; ≥30% fewer prompts) get measured on real sessions. Costs
    # one model call per card while on. Off by default; user-global only.
    auto_approve_shadow: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    # Web search provider: "duckduckgo" (keyless default) | "tavily" | "brave" (need a key).
    web_search_provider: str = "duckduckgo"
    # OpenWorker Cloud (sign-in + managed connectors). Config, never constants:
    # dev/staging/BYO-VPC deployments point these at their own instances.
    cloud_base_url: str = "https://api.openworker.com"
    # Auth0 tenant + API audience are registered identifiers, not branding: the
    # tenant name can never be renamed, and the audience must match the API
    # identifier registered in Auth0 — both keep the legacy value on purpose.
    cloud_auth_domain: str = "opencoworker.us.auth0.com"
    cloud_client_id: str = "g1l4Q1lhYWmyS03qPSf4KEJGrgq02Qam"
    cloud_audience: str = "https://api.opencoworker.app"
    # Managed relay WebSocket endpoint (Slack/GitHub inbound). Upstream defaults
    # to THEIR production relay; this fork ships it empty on purpose: a fresh
    # install must never dial the upstream cloud (the updater-endpoints rule
    # applied to the relay). Empty ⇒ relay disabled (manual Socket Mode still
    # works); point it at your own relay deployment via config.toml to enable.
    cloud_relay_ws_url: str = ""


_FIELDS = {
    "model",
    "mode",
    "max_iterations",
    "max_turn_tokens",
    "compaction_cap_tokens",
    "compaction_summary_max_tokens",
    "allowed_commands",
    "auto_allow",
    "allowed_domains",
    "auto_approve",
    "auto_approve_shadow",
    "host",
    "port",
    "web_search_provider",
    "cloud_base_url",
    "cloud_auth_domain",
    "cloud_client_id",
    "cloud_audience",
    "cloud_relay_ws_url",
}

# These fields change what consequential actions can run without a prompt, so the normal
# workspace override pass never applies them. `allowed_commands` is added separately only
# for a canonically trusted workspace; `auto_allow` and `allowed_domains` remain user-global
# only (a repo must not be able to widen the agent's command or network reach).
_GLOBAL_ONLY_FIELDS = {
    "allowed_commands",
    "auto_allow",
    "allowed_domains",
    "auto_approve",
    "auto_approve_shadow",
}
_WORKSPACE_FIELDS = _FIELDS - _GLOBAL_ONLY_FIELDS


COMPACTION_CAP_TOKENS_ENV = "COWORKER_COMPACTION_CAP_TOKENS"
COMPACTION_SUMMARY_MAX_TOKENS_ENV = "COWORKER_COMPACTION_SUMMARY_MAX_TOKENS"


def global_config_path() -> Path:
    return state_dir() / "config.toml"


def _read(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    # tomllib decodes the file as strict UTF-8 before parsing, so a config saved in a
    # legacy codepage (GBK from a Chinese editor) raises UnicodeDecodeError, not a TOML
    # error. Unreadable is unreadable: ignore it like malformed TOML rather than letting
    # it escape into callers — workspace_command_trust runs on every session connect.
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def workspace_allowed_commands(workspace: str | Path) -> list[str]:
    """Command prefixes requested by repository config; advisory until workspace trust."""
    path = Path(workspace).expanduser() / ".coworker" / "config.toml"
    value = _read(path).get("allowed_commands", [])
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(v.strip() for v in value if isinstance(v, str) and v.strip()))


def load_config(
    workspace: Optional[str | Path] = None,
    *,
    global_path: Optional[Path] = None,
    workspace_trusted: bool = False,
) -> Config:
    cfg = Config()

    g = Path(global_path) if global_path is not None else global_config_path()
    if g.is_file():
        for key, value in _read(g).items():
            if key in _FIELDS:
                setattr(cfg, key, value)
    if workspace:
        w = Path(workspace).expanduser() / ".coworker" / "config.toml"
        if w.is_file():
            for key, value in _read(w).items():
                if key in _WORKSPACE_FIELDS:
                    setattr(cfg, key, value)
            if workspace_trusted:
                cfg.allowed_commands = list(
                    dict.fromkeys(
                        [*cfg.allowed_commands, *workspace_allowed_commands(workspace)]
                    )
                )
    cfg.compaction_cap_tokens = _positive_int_setting(
        cfg.compaction_cap_tokens, "compaction_cap_tokens", COMPACTION_CAP_TOKENS_ENV
    )
    cfg.compaction_summary_max_tokens = _positive_int_setting(
        cfg.compaction_summary_max_tokens,
        "compaction_summary_max_tokens",
        COMPACTION_SUMMARY_MAX_TOKENS_ENV,
    )
    return cfg


def _positive_int_setting(
    value: Any, name: str, env_var: str
) -> Optional[int]:
    """A config.toml value overridden by `env_var`; both must be positive integers."""
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive integer, got {value!r} (config.toml)"
        )
    raw = (os.environ.get(env_var) or "").strip()
    if not raw:
        return value
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 0
    if parsed <= 0:
        raise ValueError(
            f"{name} must be a positive integer, got {raw!r} ({env_var})"
        )
    return parsed
