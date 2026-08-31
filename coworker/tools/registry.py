"""Tool registry — wraps callables (incl. aisuite toolkit tools) into a registry the
runtime owns: JSON schemas for the model, plus execution. Permission checks live in the
PermissionEngine and are applied by the turn engine, not here.

Schema generation is reused from aisuite (`Tools`) so we don't reimplement
docstring/type-hint → JSON-schema extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from aisuite.utils.tools import Tools


@dataclass
class ToolSpec:
    name: str
    schema: dict[str, Any]  # OpenAI-format function tool schema
    func: Callable[..., Any]
    metadata: Any = None  # aisuite ToolMetadata or None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        # name → the loader that would register it (see tools/deferred.py). Held-back
        # tools are absent from schemas() but NOT unknown: their names travel anyway —
        # the loader's own description lists them, a resumed transcript contains past
        # calls, and prompts elsewhere in the app name them outright (the team-lead
        # backstop asks for `sleep_until`). So a call that names one materialises the
        # set instead of failing; see `get`.
        self._deferred: dict[str, Callable[[], Any]] = {}

    def register(
        self,
        func: Callable[..., Any],
        *,
        metadata: Any = None,
        schema: Optional[dict[str, Any]] = None,
    ) -> ToolSpec:
        name = getattr(func, "__name__", None)
        if not name:
            raise ValueError("Tool function must have a __name__.")
        meta = metadata or getattr(func, "__aisuite_tool_metadata__", None)
        # Allow an explicit schema override (param or a `__coworker_schema__` attribute)
        # for tools whose signature can't be auto-converted to a valid JSON schema.
        resolved_schema = (
            schema or getattr(func, "__coworker_schema__", None) or _schema_for(func)
        )
        spec = ToolSpec(name=name, schema=resolved_schema, func=func, metadata=meta)
        self._tools[name] = spec
        return spec

    def register_all(self, funcs: list[Callable[..., Any]]) -> None:
        for func in funcs:
            self.register(func)

    def defer(self, names: list[str], loader: Callable[[], Any]) -> None:
        """Declare that `names` exist but aren't registered yet, and that calling
        `loader` registers them. Names already registered win — deferral only ever adds
        a fallback, never hides a live tool."""
        for name in names:
            self._deferred.setdefault(name, loader)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Optional[ToolSpec]:
        """The tool, materialising its deferred set first if that's where it lives.
        Every caller that resolves a tool call goes through here (permission lookup,
        parallel-safety, execution), so a model that calls a held-back tool by name gets
        it — one silent load instead of a confusing "no such tool"."""
        spec = self._tools.get(name)
        if spec is None and name in self._deferred:
            self._deferred.pop(name)()
            spec = self._tools.get(name)
        return spec

    def schemas(self) -> list[dict[str, Any]]:
        """What the model is TOLD it has. Deliberately does not materialise anything —
        the whole point of a deferred set is to stay out of the prompt until used."""
        return [spec.schema for spec in self._tools.values()]

    def execute(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"Tool not registered: {name}")
        return spec.func(**(arguments or {}))


def _schema_for(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate one OpenAI-format tool schema via aisuite's schema generator."""
    return Tools([func]).tools(format="openai")[0]
