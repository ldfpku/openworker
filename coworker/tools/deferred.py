"""On-demand tool groups: a tiny meta-tool that, on its first call, registers a held-back
set of tools into the live ToolRegistry instead of the engine loading them all eagerly.

Motivation (browser, the first adopter — wired in agent.py's build_engine): a fresh Cowork
roster carries the 9 browser_* tools whether or not the turn ever touches a browser, because
the "browser" connector has auth="none" and so counts as always-connected. The engine
re-reads `registry.schemas()` every model round-trip (engine.py's `_astream`), so a tool
registered mid-turn is callable starting the very next round-trip — deferring registration
costs nothing but one extra "load" call on the turns that actually need the toolset.
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


def deferred_toolset_description(label: str, tool_names: list[str]) -> str:
    """Default loader description — built from the ACTUAL held-back tool names so a
    per-tool toggle that drops one keeps the sentence honest instead of a hand-typed
    list silently drifting out of sync with what the toggle actually leaves enabled."""
    return (
        f"Load the in-app {label} automation toolset into this session "
        f"({', '.join(tool_names)}). Call it once before any {label} task; the tools "
        "become available immediately."
    )


def make_deferred_toolset_loader(
    registry: ToolRegistry,
    *,
    label: str,
    tool_name: str,
    deferred_tools: list[Callable[..., Any]],
    description: Optional[str] = None,
) -> Callable[..., Any]:
    """Build a `tool_name` meta-tool: its first call registers every tool in
    `deferred_tools` into `registry` — the SAME live registry object the engine re-reads
    every model round-trip — and reports what was loaded; every call after that is a
    no-op that says so instead of erroring. `deferred_tools` already carry their own
    schema + `__aisuite_tool_metadata__` (approval, risk level, …), so once registered
    they are gated exactly as if they had been there from the start — approval is keyed
    by tool name at call time against the registry, not by when the name first appeared.

    No side effect beyond mutating the registry: safe to leave ungated (no approval).
    """
    names = [t.__name__ for t in deferred_tools]
    schema = _schema(
        tool_name, description or deferred_toolset_description(label, names)
    )
    # Closure state, not the registry: register_all() is itself idempotent-unsafe to
    # call twice (harmless here since names collide, but the point is to report loaded
    # honestly on repeat calls rather than silently re-describing the same tools).
    state = {"loaded": False}

    def _load() -> str:
        if state["loaded"]:
            return f"{label.capitalize()} tools already loaded."
        registry.register_all(deferred_tools)
        state["loaded"] = True
        return f"{label.capitalize()} tools loaded: {', '.join(names)}"

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
