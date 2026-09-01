"""Engine assembly from an Agent (Code / Chat / …).

Wires the agent's base tools + permissions + AGENTS.md (workspace agents) + memory +
the skill catalog (progressive disclosure) + load_skill into a TurnEngine.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .agents import Agent, AgentContext, code_agent
from .automation import scheduling_tools
from .selfwake import selfwake_tools
from .subscriptions import subscription_tools
from .config import load_config
from .connectors import (
    connector_for_tool,
    connector_list,
    load_settings,
    make_integration_tools,
    make_send_file_tool,
    make_send_message_tool,
)
from .connectors import get_descriptor as get_connector_descriptor
from .engine import Approver, TurnEngine
from .environment import environment_context
from .memory import (
    MemoryStore,
    Scope,
    format_user_rules,
    memory_tools,
    render_memory_block,
)
from .permissions import Mode, PermissionEngine
from .project import load_agents_md
from . import session_facts
from .roots import RootDir, normalize_roots, render_context
from .providers import ProviderClient, ProviderRouter
from .overrides import RiskOverrideStore
from .secrets import SecretStore, state_dir
from .skills import SkillLoader, save_skill_tool, skill_catalog_text, skill_tools
from .tools import ToolRegistry
from .tools.ask import ask_user_tool
from .tools.deferred import make_deferred_toolset_loader
from .tools.directories import request_directory_tool
from .tools.plan import propose_plan_tool
from .tools.toolreq import request_tool_tool
from .tools.subagent import explorer_tools
from .web import make_web_fetch_tool, make_web_search_tool
from .workspace_trust import WorkspaceTrustStore
from .tools.shell import LocalExecutor
from .tools.todo import TodoList

# Appended each turn while discuss mode is active: enforcement-only read-only, with no
# pressure toward a plan proposal (that's what distinguishes it from plan mode).
_DISCUSS_MODE_CONTEXT = """\
Discuss mode is active: write and shell tools are disabled. Explore and answer freely; if
the user asks for a change, describe it in chat instead of attempting it (they can switch
to plan or approval mode to have you make it)."""

# Appended to the latest user message every turn while plan mode is active. The mode can
# flip mid-session (plan approval), so this can't live in the static instructions.
_PLAN_MODE_CONTEXT = """\
Plan mode is active: write and shell tools are blocked. Explore read-only and design an
approach. When you've committed to one, present it with `propose_plan` (what you'll change,
in which files, how you'll verify) — don't describe edits as if you were making them. If
the plan is approved, this same session switches to execution and you implement it; if
rejected, revise the plan using the feedback."""

# When-to-remember rules (MEMORY-SPEC §4.2), injected only when a memory store is wired.
# Without these, models either never call `remember` or save noise the repo already
# records. The conservative bias is deliberate: a wrong memory feels broken and creepy at
# once; a missing one merely means the user repeats themselves.
_MEMORY_GUIDANCE = """\
Memory:
- You have persistent memory across sessions. Use `remember` for durable facts: the user's \
corrections and stated preferences (include the why), and project context you couldn't \
rederive from the code. Scope by what the fact is about: facts about the user -> "global"; \
facts about the current work -> "workspace". Always pass a one-line summary (15 words max) \
alongside the full content.
- Save conservatively — a wrong memory costs more than a missing one. Save only clearly \
durable facts ("from now on", "always", "in all my chats"). Ambiguous one-off phrasing \
("I prefer simple talking"): apply it now, don't save it. But when the user explicitly \
asks you to remember something, always save it.
- Sensitive topics (health, finances, relationships, beliefs): never save silently. Ask \
first — "Want me to remember this for next time?" — and save only on a yes.
- When you save, say so in one short plain sentence in your visible reply ("I'll remember \
that you prefer short replies."). And the first time a remembered fact shapes your \
behavior in a session, note it in one quiet line ("Keeping this short since you prefer \
simple replies.") — first use only, not every message.
- Don't save what the repo already records (code structure, git history, AGENTS.md) or \
details that only matter to the current task. Use absolute dates, never "yesterday".
- Before saving, check the known-memories list: if an entry already covers it, revise that \
entry with `memory_update` instead of adding a near-duplicate; retire wrong or obsolete \
entries with `memory_forget`.
- Memories reflect when they were written. If one names a file, flag, or URL, verify it \
still exists before relying on it."""

# Injected INSTEAD of the memory guidance when the user turned memory off (§4.3).
# Off means "stop LEARNING", not "forget what you know": already-saved memories stay
# injected and usable; only the write tools are gone. Without this notice the model
# bluffs — asked to "remember" with no remember tool, it narrated a fake save through
# its todo list ("I'll remember that your favorite color is blue"), observed live
# 2026-07-28. Honesty needs the model to KNOW saving is off, not just lack the tools.
_MEMORY_OFF_NOTICE = """\
Saving new memories is turned off in this user's Settings. What you already know about \
them (the known-memories list, if any) is still true and you should keep using it — but \
you have no way to save, change, or delete anything, and nothing new from this \
conversation will carry over to future ones. If the user asks you to remember something \
new, state both halves plainly: you'll keep it in mind for the rest of this conversation, \
but it won't be saved once the conversation ends — they can turn saving back on in \
Settings ▸ Memory. Never imply you saved, noted, or will remember anything new."""

# UX-015 (§33): the GUI interleaves these status lines with humanized tool rows inside a
# collapsed "turn" — they're what the user reads while the agent works. Universal (appended
# for every persona); models that ignore it degrade gracefully to a turn with no narration.
_NARRATION_GUIDANCE = """\
Narration: before each batch of tool calls, write ONE short plain sentence saying what \
you're doing and why (e.g. "Checking what merged since yesterday's digest."). It is shown \
to the user as live progress. Don't narrate trivial single-call follow-ups, don't repeat \
the previous line, and never let narration replace your final answer.

Language: reply (and narrate) in the language the user writes in."""

# A bare "hey" answered with a bare "hey" makes a specialist read as an empty chat box
# (owner catch 2026-08-24). First contact is the one moment to show what this coworker
# is for — after that, greetings stay lightweight.
_FIRST_CONTACT_GUIDANCE = """\
First contact: if the user's first message is a simple hello or open-ended ("hey", "what \
can you do?") rather than a task, don't just say hello back — say in one or two \
sentences what you do in this role, then offer two or three concrete starting points as \
an ask_user question (short option labels, phrased for this session's context — \
workspace, connected tools — and leave the free-text answer available so the user can \
type their own direction). A picked option is a clear brief: start on it. Keep it short \
and skip all of this when the user already gave you a task."""


def _enabled_connector_tools(secrets: SecretStore) -> tuple[set[str], set[str]]:
    connectors = {c["name"]: c for c in connector_list(secrets)}
    enabled_connectors = {
        name
        for name, c in connectors.items()
        if c.get("connected") and c.get("enabled")
    }
    enabled_tools = {
        tool["name"]
        for c in connectors.values()
        if c.get("name") in enabled_connectors
        for tool in c.get("tools", [])
        if tool.get("enabled")
    }
    return enabled_connectors, enabled_tools


def _group_by_connector(
    tools: list[Callable[..., Any]],
) -> tuple[list[Callable[..., Any]], dict[str, list[Callable[..., Any]]]]:
    """Partition an already-filtered connector tool list into (register now, hold back
    per connector). Runs AFTER `make_integration_tools`' own filtering, so this never
    re-decides what's connected/enabled — it only decides WHEN an already-approved tool
    registers. A tool no connector claims (shouldn't happen, but a new toolset could
    land before its `TOOL_TO_CONNECTOR` entry) registers eagerly rather than vanishing
    behind a loader nobody knows to call."""
    kept: list[Callable[..., Any]] = []
    held: dict[str, list[Callable[..., Any]]] = {}
    for t in tools:
        connector = connector_for_tool(t.__name__)
        if connector:
            held.setdefault(connector, []).append(t)
        else:
            kept.append(t)
    return kept, held


def _mentions_managed_tool(agent: Agent) -> bool:
    """Does this persona actually work with a pinned-catalog tool? Checked against the
    persona's own prompt and declared skill names — a persona that never says `gitleaks`
    is never going to ask us to install it, and shipping the request tool to it is pure
    prompt cost. Cheap substring test on text built once at engine build."""
    from .toolchain import MANAGED

    haystack = " ".join(
        [agent.system_prompt or "", " ".join(getattr(agent, "skills", None) or [])]
    ).lower()
    return any(name.lower() in haystack for name in MANAGED)


def _loaded_skill_names(messages: list[dict[str, Any]]) -> set[str]:
    """Skills whose instructions successfully entered THIS conversation (a load_skill call
    with a non-error result). Drives the disable countermand: a menu quietly shrinking is
    passive, but instructions already in history keep steering the model unless it is
    explicitly asked to stop."""
    import json as _json

    results: dict[str, str] = {}
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            content = m.get("content")
            results[m["tool_call_id"]] = (
                content if isinstance(content, str) else _json.dumps(content)
            )
    loaded: set[str] = set()
    for m in messages:
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        for tc in m["tool_calls"]:
            fn = tc.get("function") or {}
            if fn.get("name") != "load_skill":
                continue
            try:
                name = str(_json.loads(fn.get("arguments") or "{}").get("name", ""))
            except Exception:
                continue
            result = results.get(tc.get("id", ""), "")
            if name and '"instructions"' in result:
                loaded.add(name)
    return loaded


def _skill_dirs(workspace: Optional[Path]) -> list[Path]:
    dirs = [state_dir() / "skills"]
    if workspace is not None:
        dirs.append(workspace / ".coworker" / "skills")
    return dirs


# One clause per tool that ToolRegistry.hold_back() can hide, keyed by the name(s) that
# have to have actually been held back for the clause to be true. A pair sharing one
# clause (the two shell-task helpers, the two memory revision tools) only prints when
# BOTH names were held back — which is always, since they're only ever registered
# together — so the sentence never claims a tool exists that this session doesn't have.
_HOLD_BACK_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("request_directory",), "request_directory(reason) — ask the user to grant another folder"),
    (("send_file",), "send_file — deliver a workspace file into a connected chat"),
    (("save_skill",), "save_skill — propose saving a reusable skill"),
    (
        ("shell_task_output", "shell_task_kill"),
        "shell_task_output(task_id) / shell_task_kill(task_id) — read or stop a "
        "background shell task",
    ),
    (
        ("memory_update", "memory_forget"),
        "memory_update / memory_forget — revise or retire a saved memory",
    ),
    (("memory_read",), "memory_read — search saved memories"),
]


def _hold_back_hint(held_back: list[str]) -> str:
    """One line reminding the model that a held-back tool still answers to its name —
    the whole risk hold_back() takes on. Built ONLY from what `held_back` actually
    contains (never a fixed string), so a session missing a capability (no memory store,
    no messaging, the lead role) doesn't get told a tool exists that it doesn't. Returns
    "" when nothing was held back, or when the only thing held back was `propose_plan` —
    that one is named by `_PLAN_MODE_CONTEXT` instead, on the turns it actually matters."""
    held = set(held_back)
    entries = [text for names, text in _HOLD_BACK_HINTS if held.issuperset(names)]
    if not entries:
        return ""
    return (
        "Some tools are registered but not listed to save context; call them directly "
        "by name when needed: " + "; ".join(entries) + "."
    )


def build_engine(
    *,
    agent: Agent,
    workspace: Optional[str | Path] = None,
    model: str = "gpt-5.6-sol",
    mode: Mode = Mode.INTERACTIVE,
    approver: Optional[Approver] = None,
    provider: Optional[ProviderClient] = None,
    allowed_commands: Optional[list[str]] = None,
    max_iterations: Optional[int] = None,
    model_settings: Optional[dict[str, Any]] = None,
    memory_store: Optional[MemoryStore] = None,
    # Twentieth pass: the project key memory loads/saves under. Defaults to the
    # workspace path; the manager passes the resolved key (binding > git > path)
    # so all worktrees of a repo share one memory and named bindings work.
    memory_workspace: Optional[str] = None,
    # MEMORY-SPEC §5.1: called with the MemoryItem right after `remember` persists it —
    # the manager uses this to push the memory_saved event that powers the save toast.
    on_memory_saved: Optional[Any] = None,
    # MEMORY-SPEC §6: the user's standing rules (Settings textarea). Injected verbatim
    # above auto memories; independent of the memory on/off switch. No tool writes it.
    # A CALLABLE is read per turn (the server passes one so a Settings edit reaches
    # conversations already open); a plain string is a fixed value for CLI/tests.
    user_rules: Optional[Any] = None,
    # True when the user turned memory OFF in Settings (vs. memory simply not wired):
    # injects the honesty notice so the model says so instead of faking a save.
    memory_off: bool = False,
    # LIVE saving switch, consulted per write so turning memory off applies to
    # conversations already running (the registry is fixed at build, so the tool stays
    # and refuses). Same pattern as the skills menu's live filter.
    memory_saving_enabled: Optional[Any] = None,
    messages: Optional[list[dict[str, Any]]] = None,
    extra_tools: Optional[list[Any]] = None,
    secrets: Optional[SecretStore] = None,
    task_store: Optional[Any] = None,
    wake_store: Optional[Any] = None,
    session_id: Optional[str] = None,
    audit_sink: Optional[Any] = None,
    roots: Optional[list] = None,
    directory_requester: Optional[Any] = None,
    plan_approver: Optional[Any] = None,
    question_asker: Optional[Any] = None,
    tool_requester: Optional[Any] = None,
    team_approver: Optional[Any] = None,
    items_approver: Optional[Any] = None,
    subscription_store: Optional[Any] = None,
    channel_buffer: Optional[Any] = None,
    routing_targets: Optional[list[str]] = None,
    connector_filter: Optional[set[str]] = None,
    # A set (static snapshot) or a zero-arg callable (live, re-evaluated per load_skill).
    skill_filter: Optional[set[str] | Callable[[], set[str]]] = None,
    # Auto-Approve flags (spec Part 8 / §1.5). None ⇒ read the config.toml value; the server
    # passes its prefs-backed booleans so the GUI Settings toggle takes effect. Both stores
    # are user-global, preserving the "a repo can't enable this" invariant.
    auto_approve: Optional[bool] = None,
    auto_approve_shadow: Optional[bool] = None,
    # Persona-carried skill folders (OPE-58): the bundle's skills/ dir joins the loader so
    # its skills are readable by load_skill, not just listed by the filter.
    extra_skill_dirs: Optional[list[str | Path]] = None,
) -> TurnEngine:
    ws = Path(workspace).expanduser().resolve() if workspace else None
    if agent.requires_folder and ws is None:
        raise ValueError(f"agent '{agent.name}' requires a workspace")

    # The session's directories. Explicit `roots` (orphan Cowork: scratch + added folders) wins;
    # otherwise the single workspace is the sole writable root. One shared, mutable list flows to
    # the file tools, the permission engine, and the context injector so add/remove is seen by all.
    if roots:
        root_list: list[RootDir] = normalize_roots(roots)
    elif ws is not None:
        root_list = [RootDir(path=ws, writable=True)]
    else:
        root_list = []

    workspace_trusted = bool(ws and WorkspaceTrustStore().is_trusted(ws))
    config = load_config(ws, workspace_trusted=workspace_trusted)
    executor = LocalExecutor(cwd=ws) if ws is not None else None
    todo = TodoList()
    context = AgentContext(
        workspace=ws, executor=executor, todo=todo, roots=root_list or None
    )

    registry = ToolRegistry()
    registry.register_all(agent.build_tools(context))
    # MCP / connector tools (supplied by the manager) carry their own metadata + schema.
    if extra_tools:
        registry.register_all(extra_tools)
    # Messaging personas (Cowork / Ops / MyHelper) expose send_message; MyHelper also uses it as
    # the reply path for inbound Telegram/Slack super-agent sessions.
    secrets = secrets or SecretStore()
    if agent.messaging and any(s.enabled for s in load_settings(secrets).values()):
        registry.register(make_send_message_tool(secrets))
        # send_file (§34): hand deliverables into the chat — same targets, but its OWN
        # approval surface (a thread's standing send_message grant never covers uploads).
        registry.register(
            make_send_file_tool(secrets, workspace=ws, roots=root_list or None)
        )
        # Channel subscriptions (inbound): listen to a channel, catch up, (un)subscribe. The agent
        # obtains a channel via ask_user or from a channel message it's reacting to.
        # Deferred like the connector sets: 4 schemas (~1,300 chars) for an explicitly
        # task-shaped action — "start listening to this channel" — that a turn either
        # sets out to do or never touches. The loader's own description names the four,
        # and ToolRegistry.defer() means a model that calls one directly still gets it.
        if subscription_store is not None and channel_buffer is not None and session_id:
            registry.register(
                make_deferred_toolset_loader(
                    registry,
                    label="subscription",
                    title="Channel subscription",
                    tool_name="load_subscription_tools",
                    deferred_tools=subscription_tools(
                        subscription_store,
                        session_id,
                        channel_buffer,
                        routing_targets=routing_targets,
                    ),
                )
            )
    # Surfaces with a multi-root workspace can ask the user mid-task for another folder.
    if root_list:
        registry.register(request_directory_tool())
    # A persona that runs one of the PINNED catalog tools needs a way to ask for it
    # instead of silently dropping the check (OPE-85). But the catalog is a closed set of
    # three security scanners (`toolchain.MANAGED`), so registering this for every session
    # with a shell put ~1,150 chars of schema in front of models that could never
    # legitimately call it — for ANY other missing CLI the tool's own text says to install
    # it with the shell instead. Gated on the persona actually naming one, which is
    # derived rather than hand-maintained: add a managed tool and the personas that talk
    # about it pick this up automatically.
    if executor is not None and _mentions_managed_tool(agent):
        registry.register(request_tool_tool())
    if agent.connectors:
        enabled_connectors, enabled_tools = _enabled_connector_tools(secrets)
        # Least-privilege grant (OPE-93): a persona with an allowlist gets ONLY the
        # connectors it declared — an undeclared connector's tools never enter the
        # session, no matter what the user has connected. True = general personas
        # (Cowork) that legitimately drive whatever is connected.
        if agent.connectors is not True:
            enabled_connectors = enabled_connectors & set(agent.connectors)
        # Per-session connection hierarchy (UI-REFRESH §4.3): when the caller supplies the session's
        # effective connector set, intersect it so only effective-enabled connectors expose tools.
        # Default None preserves CLI / direct callers (no per-session restriction).
        if connector_filter is not None:
            enabled_connectors = enabled_connectors & connector_filter
        connector_tools = make_integration_tools(
            secrets,
            enabled_connectors=enabled_connectors,
            enabled_tools=enabled_tools,
            roots=root_list or None,
        )
        # Progressive disclosure (the industry-standard answer to prompt bloat): EVERY
        # connector's tools are held back behind one `load_<connector>_tools` meta-tool
        # instead of being declared up front. Tool schemas are ~85% of a fresh session's
        # prompt, connector schemas are most of that, and a first turn almost never
        # touches an integration — yet with no prompt caching (several OpenAI-compatible
        # vendors report none) that whole block is re-billed at full price every single
        # round trip. A loader costs ~1/10 of the set it replaces and one extra round
        # trip on the turns that DO use it. Started as browser-only; generalised because
        # the cost scales with what the user has connected (Asana alone is 13 schemas).
        # The split happens AFTER every filter above, so per-tool toggles, the persona
        # allowlist, and session mutes all still gate tools exactly as before; only WHEN
        # they register changes. A connector whose tools were all filtered away gets no
        # loader either — a loader for an empty set is just a dead end.
        connector_tools, deferred_by_connector = _group_by_connector(connector_tools)
        registry.register_all(connector_tools)
        for connector, held in deferred_by_connector.items():
            descriptor = get_connector_descriptor(connector)
            registry.register(
                make_deferred_toolset_loader(
                    registry,
                    label=connector,
                    title=(descriptor.title if descriptor else None),
                    tool_name=f"load_{connector}_tools",
                    deferred_tools=held,
                )
            )
    # Web search + fetch: research tools for every agent (keyless DuckDuckGo default).
    registry.register(make_web_search_tool(secrets))
    registry.register(make_web_fetch_tool())
    # ask_user: the universal human-in-the-loop Q&A primitive (every agent; engine-intercepted).
    if question_asker is not None:
        registry.register(ask_user_tool())
    # Route by the model's `provider:` prefix (OpenAI default, Ollama, …). The manager normally
    # passes its shared router; this fallback covers the TUI / direct build_engine() callers.
    # Resolved here (not at engine construction) because the explorer subagent captures it.
    provider = provider or ProviderRouter(secrets, default_provider="openai")
    # Repo-focused personas can fan broad research out to read-only explorer subagents, keeping
    # their own context for the actual change.
    if agent.subagents and ws is not None:
        registry.register_all(
            explorer_tools(
                workspace=ws,
                provider=provider,
                model=model,
                model_settings=model_settings,
            )
        )
    # Scheduling: opted-in surfaces with a workspace can set up scheduled tasks (origin = this
    # session). Code stays out (it fans out to explorers instead).
    # Self-wake: scheduling surfaces can suspend + schedule their own resumption (timer /
    # on-completion / on-event). The scheduler tick resumes due wakes.
    # Both go behind ONE `load_scheduling_tools` loader, for the same reason the connector
    # sets do: 7 schemas (~1,050 tokens, a sixth of a fresh Cowork prompt) that a normal
    # turn never calls, re-billed every round trip. They are one group because "run this
    # later" and "wake me when" are the same intent arriving at the model together.
    timing_tools: list[Callable[..., Any]] = []
    if task_store is not None and ws is not None and agent.scheduling:
        origin = {
            "surface": agent.name,
            "session_id": session_id or "",
            "workspace": str(ws),
            "agent": agent.name,
        }
        timing_tools += scheduling_tools(
            task_store, origin=origin, default_workspace=str(ws)
        )
    if wake_store is not None and session_id and agent.scheduling:
        timing_tools += selfwake_tools(wake_store, session_id)
    if timing_tools:
        registry.register(
            make_deferred_toolset_loader(
                registry,
                label="scheduling",
                title="Scheduling",
                tool_name="load_scheduling_tools",
                deferred_tools=timing_tools,
            )
        )

    instructions = f"{agent.system_prompt}\n\n{_NARRATION_GUIDANCE}\n\n{_FIRST_CONTACT_GUIDANCE}"
    if ws is not None:
        instructions = f"{instructions}\n\n{environment_context(ws)}"
        conventions = load_agents_md(ws)
        if conventions:
            instructions = f"{instructions}\n\n{conventions}"

    # The user's own standing instructions, read once here: like the memories below,
    # they're session-stable knowledge. Edits apply to NEW conversations (the Settings
    # copy says exactly that), never mid-conversation.
    rules_block = format_user_rules(
        (user_rules() if callable(user_rules) else user_rules) or ""
    )
    if rules_block:
        instructions = f"{instructions}\n\n{rules_block}"

    # The live saving switch. The callable (server) beats the build-time flag (CLI/tests):
    # the setting can flip EITHER WAY mid-conversation, so nothing about it may be baked
    # into the fixed registry or the static instructions (owner-hit 2026-07-28, both
    # directions: off kept saving, then on kept claiming it was off).
    def _saving_enabled() -> bool:
        if memory_saving_enabled is not None:
            return bool(memory_saving_enabled())
        return not memory_off

    if memory_store is not None:
        # Always the full toolset: the registry is fixed at build, so a session born
        # while saving was off must still be able to save the moment it's turned on.
        # Enforcement is the tools' own live check, not their absence.
        mem_ws = memory_workspace or (str(ws) if ws else None)
        registry.register_all(
            memory_tools(
                memory_store,
                workspace=mem_ws,
                on_saved=on_memory_saved,
                saving_enabled=_saving_enabled,
            )
        )
        instructions = f"{instructions}\n\n{_MEMORY_GUIDANCE}"
        # What the coworker KNOWS is fixed at session start (MEMORY-SPEC §7.1): a
        # conversation's knowledge must not shift underfoot — a fact it referenced ten
        # turns ago cannot silently vanish — and the system prompt is the cached prefix,
        # so the facts are processed once instead of re-sent every turn. Deletions reach
        # NEW conversations; the UI says so rather than pretending otherwise.
        remembered = memory_store.list(scope=Scope.GLOBAL)
        if mem_ws is not None:
            remembered += memory_store.list(scope=Scope.WORKSPACE, workspace=mem_ws)
        block = render_memory_block(remembered)
        if block:
            instructions = f"{instructions}\n\n{block}"

    # Persona dirs come FIRST so a user's global/workspace copy of the same name shadows
    # the bundle's (later dirs overwrite earlier in the loader).
    skill_loader = SkillLoader([Path(d) for d in (extra_skill_dirs or [])] + _skill_dirs(ws))
    # Per-session effective menu (SKILLS-SPEC §3). The manager passes a CALLABLE so
    # load_skill consults the LIVE state per call (a Settings disable applies to running
    # sessions; a skill created after this build is still loadable). The catalog itself
    # is injected per turn via context_provider (below), NOT here — so the menu the model
    # sees is also live: skill changes apply from the next message, no new session needed.
    # Default None preserves CLI / direct callers.
    # `roots=root_list`: loading a skill mounts that skill's folder as a read-only
    # resource root, so its bundled references/scripts are readable by the file tools.
    registry.register_all(
        skill_tools(skill_loader, allowed=skill_filter, roots=root_list or None)
    )
    # The worker-authors door (SKILLS-SPEC §5.2): save_skill proposes installing a finished
    # skill; requires_approval routes it through the standard approval card, so the review-
    # before-save rule holds without any bespoke plumbing. Bundled files may only come from
    # this session's roots.
    registry.register(
        save_skill_tool(
            allowed_dirs=[r.path for r in (root_list or [])] or ([ws] if ws else [])
        )
    )

    # User-local risk overrides (mainly to relax MCP's conservative default). Empty store →
    # no-op; never written by persona loading (the no-self-grant rule).
    risk_overrides = RiskOverrideStore(state_dir() / "risk_overrides.json").resolver()
    permissions = PermissionEngine(
        workspace_root=ws or (root_list[0].path if root_list else Path.cwd()),
        mode=mode,
        # `[]` is an explicit deny-by-default override, not a request to fall back to config.
        allowed_commands=(
            allowed_commands if allowed_commands is not None else config.allowed_commands
        ),
        auto_allow_tools=set(config.auto_allow),
        allowed_domains=list(config.allowed_domains),
        roots=root_list or None,
        risk_overrides=risk_overrides,
    )
    # The plan-mode exit door — mutually exclusive with the board's decomposition
    # gate, DERIVED from the team trait (owner call 2026-08-16): a lead never
    # implements, so plan mode is meaningless for it, and shipping both tools made
    # the lead pick the wrong one (dogfood-hit: propose_plan denied outside plan
    # mode). Solo/worker personas keep propose_plan as always (mode can flip
    # mid-session; the engine rejects the call outside plan mode).
    if agent.team != "lead":
        registry.register(propose_plan_tool())

    # The lead's gates: propose_work_items (decomposition → items on approval, any
    # mode) and propose_team (staffing → pre-spawn on approval).
    if agent.team == "lead":
        from .teams.tools import propose_team_tool, propose_work_items_tool

        registry.register(propose_work_items_tool())
        registry.register(propose_team_tool())

    # Third pass on prompt budget (2026-09-01): a handful of tools are registered above
    # like everything else, then immediately pulled back behind ToolRegistry.hold_back()
    # — out of schemas() until the model names one directly, at which point get() puts it
    # right back (same one-silent-load contract defer() already gives connector sets).
    # These are exactly the tools a normal turn never opens with: granting another
    # folder, delivering a file into chat, proposing a skill, polling/killing a
    # background shell task, revising or searching saved memories. hold_back() skips
    # names this session never registered in the first place (no messaging ⇒ no
    # send_file, no memory_store ⇒ no memory_*), so the call is safe to make unconditionally.
    # propose_plan is the one name gated by mode rather than by registration: a session
    # that STARTS in Mode.PLAN needs it on the very first turn, so it's left alone there;
    # everywhere else it's held back too (a mode flip INTO plan mid-session is handled by
    # the server/TUI /mode paths calling registry.get("propose_plan") to materialize it —
    # see coworker/server/app.py and coworker/tui/app.py). The lead role never registers
    # propose_plan at all (line 554 above), so it's simply absent from `held_back` too —
    # hold_back skipping an unregistered name is the same no-op that already protects
    # that gate.
    hold_back_names = [
        "request_directory",
        "save_skill",
        "send_file",
        "shell_task_output",
        "shell_task_kill",
        "memory_update",
        "memory_forget",
        "memory_read",
    ]
    if mode is not Mode.PLAN:
        hold_back_names.append("propose_plan")
    held_back = registry.hold_back(hold_back_names)
    hold_back_hint = _hold_back_hint(held_back)
    if hold_back_hint:
        instructions = f"{instructions}\n\n{hold_back_hint}"

    # Per-turn ephemeral context, appended to the latest user message since mid-thread system
    # messages aren't reliable across providers. Three producers: the plan-mode reminder (mode can
    # flip mid-session, so it's checked each turn, not baked into the instructions), the live
    # directory list (any multi-root session can gain folders mid-session), and the
    # memory-SAVING notice (same reason as plan mode — the switch flips either way mid-chat).
    # Note what is NOT here: the memories and the user's rules. Those are knowledge, fixed at
    # session start (§7.1).
    roots_context = (lambda: render_context(root_list)) if root_list else None

    # Late-bound engine ref: the closure needs the conversation history (for the disable
    # countermand) but the engine is constructed after the closure. Filled below.
    _engine_box: list = []

    def context_provider() -> str:
        # Live clock, every turn (owner ruling 2026-08-20): the environment block's
        # "Today's date" is a session-START snapshot — stale for long-lived/self-waking
        # sessions — and carries no time of day, which absolute scheduling
        # (sleep_until, scheduled tasks) needs to compute wake times.
        now = datetime.now().astimezone()
        parts = [f"Now: {now.strftime('%Y-%m-%d %H:%M')} ({now.tzname()})"]
        if permissions.mode is Mode.PLAN:
            parts.append(_PLAN_MODE_CONTEXT)
        elif permissions.mode is Mode.DISCUSS:
            parts.append(_DISCUSS_MODE_CONTEXT)
        # Only the SAVING switch is per-turn (§4.3): it governs an action, not
        # knowledge, so it must bite the moment the user flips it. What the coworker
        # knows stays fixed for the session — see the instructions built above.
        if memory_store is not None and not _saving_enabled():
            parts.append(_MEMORY_OFF_NOTICE)
        if roots_context is not None:
            ctx = roots_context()
            if ctx:
                parts.append(ctx)
        # Live skill menu (SKILLS-SPEC §4.1): recomputed every turn like the roots list, so
        # a skill installed/enabled/disabled mid-session applies from the NEXT MESSAGE —
        # no new session, no lost context.
        skill_loader.rescan()
        allowed = skill_filter() if callable(skill_filter) else skill_filter
        skills_ctx = skill_catalog_text(skill_loader, allowed=allowed)
        if skills_ctx:
            parts.append(skills_ctx)
        # Disable countermand (§3): instructions already loaded into this conversation keep
        # steering the model even after the skill is turned off/deleted — history can't be
        # un-read. So a loaded-but-no-longer-available skill gets an explicit stop note,
        # recomputed fresh each turn (re-enable → the note disappears; never persisted).
        eng = _engine_box[0] if _engine_box else None
        if eng is not None:
            available = set(skill_loader.names()) if allowed is None else set(allowed)
            for name in sorted(_loaded_skill_names(eng.messages) - available):
                parts.append(
                    f'Note: the skill "{name}" has been disabled by the user — stop '
                    "following its instructions from here on."
                )
        return "\n\n".join(parts)

    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model=model,
        instructions=instructions,
        approver=approver,
        # Stop kills the in-flight foreground shell command, not just the loop.
        interrupt_hooks=[executor.interrupt_now] if executor is not None else None,
        max_iterations=(
            max_iterations if max_iterations is not None else config.max_iterations
        ),
        max_turn_tokens=config.max_turn_tokens,
        model_settings=model_settings,
        messages=messages,
        audit_sink=audit_sink,
        context_provider=context_provider,
        directory_requester=directory_requester,
        plan_approver=plan_approver,
        question_asker=question_asker,
        tool_requester=tool_requester,
        team_approver=team_approver,
        items_approver=items_approver,
    )
    engine.executor = executor  # type: ignore[attr-defined]
    engine.todo = todo  # type: ignore[attr-defined]
    engine.agent_name = agent.name  # type: ignore[attr-defined]
    engine.roots = root_list  # type: ignore[attr-defined]  # shared list; Slice C mutates in place
    # Session facts (spec Part 0 / §2.4): freeze the known world NOW, before the agent has
    # acted. Freezing is the whole point — compared against live state, an agent that runs
    # `git remote add backup https://attacker.net/…` would make its own destination look
    # familiar. Nothing consumes this in v1; ingestion is recorded to the audit log only.
    engine.session_facts = session_facts.SessionFacts(
        world=session_facts.capture(
            roots=root_list,
            allowed_domains=config.allowed_domains,
            workspace=ws,
        )
    )

    # §1.9: the web_search approval card names the LIVE destination ("Queries go to your
    # configured search provider (currently: ‹name›)"). Resolved when the card is raised,
    # not at session start, so a mid-session Settings change shows through.
    def _approval_extras(tool_name: str, _arguments: dict) -> dict:
        if tool_name == "web_search":
            from .web import provider_name

            return {"search_provider": provider_name(secrets)}
        return {}

    engine.approval_extras = _approval_extras
    # Auto-Approve reviewer (spec Part 8). Attached only when the user-global flag is on —
    # a repo config can never enable it (`auto_approve` is in _GLOBAL_ONLY_FIELDS, same
    # rule as `auto_allow`). With no reviewer attached, Mode.AUTO_APPROVE behaves exactly
    # like INTERACTIVE, which is also the fallback for unattended sessions and after the
    # per-turn retry guard trips (engine._reviewer_active). Uses the session's own
    # provider and model: no second key, and if it's trusted to drive the agent it's
    # strong enough to review it (§1.5).
    #
    # The two flags may be overridden by the caller (the GUI Settings toggle persists them
    # to the user-global prefs store, which the server reads and passes here); None ⇒ take
    # the config.toml value. Both stores are user-global, so a repo still can't turn either
    # on regardless of which path set it.
    live_on = auto_approve if auto_approve is not None else getattr(config, "auto_approve", False)
    shadow_on = (
        auto_approve_shadow
        if auto_approve_shadow is not None
        else getattr(config, "auto_approve_shadow", False)
    )
    if live_on or shadow_on:
        from .reviewer import Reviewer

        engine.reviewer = Reviewer(
            provider=provider,
            model=model,
            known_world=engine.session_facts.world.render(),
        )
        # Shadow evaluation (Part 6 step 3): with only the shadow flag on, the reviewer is
        # attached but the LIVE path stays off unless the session is actually in
        # Mode.AUTO_APPROVE — shadow verdicts are recorded on approval cards in any mode.
        engine.reviewer_shadow = bool(shadow_on)
    engine.audit_context = {
        "session_id": session_id or "",
        "agent": agent.name,
        "workspace": str(ws) if ws else "",
    }
    engine.skill_loader = skill_loader  # type: ignore[attr-defined]
    _engine_box.append(engine)  # late-bind for the countermand (see context_provider)
    return engine


def build_code_engine(**kwargs: Any) -> TurnEngine:
    """Back-compat shim: build the Code agent's engine."""
    return build_engine(agent=code_agent(), **kwargs)
