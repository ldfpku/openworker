"""On-demand tool groups: a tiny meta-tool that, on its first call, registers a held-back
set of tools into the live ToolRegistry instead of the engine loading them all eagerly.

Motivation: tool schemas are ~85% of a fresh session's prompt, and the prompt is re-sent
in full on every round trip — at full price wherever the provider does no prompt caching.
Browser was the first adopter (9 tools carried by every Cowork session because the
"browser" connector has auth="none" and so counts as always-connected); agent.py now
defers every connector's toolset plus the scheduling/self-wake group the same way.

The engine re-reads `registry.schemas()` every model round-trip (engine.py's `_astream`),
so a tool registered mid-turn is callable starting the very next round-trip — deferring
costs nothing but one extra "load" call on the turns that actually need the toolset. And
the held-back names stay known to the registry (`ToolRegistry.defer`), so a model that
calls one directly gets the set loaded under it rather than a "no such tool" error.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import aisuite as ai

from .registry import ToolRegistry


def _schema(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def deferred_toolset_description(title: str, tool_names: list[str]) -> str:
    """Default loader description — built from the ACTUAL held-back tool names so a
    per-tool toggle that drops one keeps the sentence honest instead of a hand-typed
    list silently drifting out of sync with what the toggle actually leaves enabled.
    Deliberately terse: this sentence is itself prompt, paid on every round trip, and
    the whole point of the loader is to cost far less than the set it stands in for."""
    return (
        f"Load {title} tools into this session: {', '.join(tool_names)}. "
        f"Call once before the first {title} action; they work immediately after."
    )


def make_deferred_toolset_loader(
    registry: ToolRegistry,
    *,
    label: str,
    tool_name: str,
    deferred_tools: list[Callable[..., Any]],
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[..., Any]:
    """Build a `tool_name` meta-tool: its first call registers every tool in
    `deferred_tools` into `registry` — the SAME live registry object the engine re-reads
    every model round-trip — and reports what was loaded; every call after that is a
    no-op that says so instead of erroring. `deferred_tools` already carry their own
    schema + `__aisuite_tool_metadata__` (approval, risk level, …), so once registered
    they are gated exactly as if they had been there from the start — approval is keyed
    by tool name at call time against the registry, not by when the name first appeared.

    `title` is the human name used in the description and the load confirmation
    ("GitHub", not "github"); it defaults to a capitalised `label`, which is right for
    one-word connector ids and wrong for `google_calendar`, hence the descriptor lookup
    at the call site.

    No side effect beyond mutating the registry: safe to leave ungated (no approval).
    """
    names = [t.__name__ for t in deferred_tools]
    title = title or label.capitalize()
    schema = _schema(
        tool_name, description or deferred_toolset_description(title, names)
    )
    # Closure state, not the registry: register_all() is itself idempotent-unsafe to
    # call twice (harmless here since names collide, but the point is to report loaded
    # honestly on repeat calls rather than silently re-describing the same tools).
    state = {"loaded": False}

    def _load() -> str:
        if state["loaded"]:
            return f"{title} tools already loaded."
        registry.register_all(deferred_tools)
        state["loaded"] = True
        return f"{title} tools loaded: {', '.join(names)}"

    # The set's names are known to the registry even while its tools are held back, so a
    # call that names one loads the set instead of bouncing off "no such tool".
    registry.defer(names, _load)

    _load.__name__ = tool_name
    _load.__coworker_schema__ = schema
    _load.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name=tool_name,
        category="meta",
        risk_level="low",
        capabilities=[label],
        requires_approval=False,
    )
    _load.__doc__ = schema["function"]["description"]
    return _load
