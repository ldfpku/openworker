"""Provider-agnostic model access layer.

The runtime never imports a provider SDK directly — it talks to a `ProviderClient`.
Implementations: `OpenAIResponsesProvider` (native OpenAI via `/v1/responses`),
`OpenAIProvider` (Chat Completions — the compat world), and the native
Anthropic/Gemini/Bedrock/Vertex providers, all selected by the registry/router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

# Opening tag of the ephemeral per-turn context block the engine appends as its own
# trailing user message (engine._outbound_messages). Shared here so providers can
# recognize the block — it changes every turn (live clock, skills rescan), so cache
# breakpoints must land on the last message BEFORE it, never on it.
SYSTEM_CONTEXT_OPEN = "<system-context>"


def bounded_client(client: Any, timeout: Any) -> Any:
    """A per-call clone of an SDK client with automatic retries off, for a call that
    carries an explicit `timeout`.

    A timeout is only a wall-clock bound if nothing silently multiplies it. The OpenAI SDK
    defaults to `max_retries=2` and counts a timed-out request as retryable, so a caller
    that asks for 60s can still be kept waiting 180s — which is exactly how a one-shot
    helper (Enhance prompt, auto-title) turns into an unexplained hang instead of a clean
    failure. `with_options` returns a shallow copy sharing the same HTTP pool, so this
    costs nothing and never mutates the cached client other calls are using.

    `timeout` None (every normal turn) returns the client untouched: the agent loop wants
    the SDK's own resilience. Clients without `with_options` (test fakes, hand-rolled
    stand-ins) are returned unchanged too — the request-level timeout still applies there,
    it just isn't protected from retries.
    """
    if timeout is None:
        return client
    with_options = getattr(client, "with_options", None)
    if not callable(with_options):
        return client
    try:
        return with_options(max_retries=0)
    except Exception:  # noqa: BLE001 - a clone we can't make is no reason to fail the call
        return client


@dataclass
class ToolCall:
    """A single tool call requested by the model, with parsed arguments."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """Normalized token counts for one model round-trip.

    `input` counts only fresh (uncached) prompt tokens; cached prompt tokens are
    split into `cache_read`/`cache_write`. Providers that don't report a cache
    split (Ollama, most compat vendors) leave the cache fields at 0. `output`
    includes thinking tokens where the vendor bills them as output (Gemini).
    """

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def context_tokens(self) -> int:
        """Prompt-side total — what actually occupied the context window."""
        return self.input + self.cache_read + self.cache_write

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


@dataclass
class AssistantTurn:
    """One assistant response: free text and/or a set of tool calls."""

    text: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    raw: Any = field(default=None, repr=False, compare=False)
    # The model's thinking text (DeepSeek reasoning_content, Gemini thought summaries, …).
    # Display-only: persisted on the assistant message as the `reasoning` sidecar and shown
    # in the GUI, but stripped before every provider call — never replayed as context.
    reasoning: Optional[str] = None
    # Provider-private sidecars to persist on the canonical assistant message
    # (underscore-prefixed keys, e.g. `_gemini` thought signatures). Contract: the
    # owning provider consumes its own key when converting history; every other
    # provider must strip or ignore foreign underscore keys before its wire call.
    extras: dict[str, Any] = field(default_factory=dict)
    # Token counts for this round-trip, normalized across providers. None when the
    # backend didn't report usage (some compat servers) — never guessed.
    usage: Optional[TokenUsage] = None
    # True when the STREAM ended without the provider ever reporting a finish reason —
    # i.e. the response was severed mid-flight rather than completed. Only providers that
    # always report one on a clean finish set this (OpenAI-compatible chat streaming,
    # where the last choice chunk always carries `finish_reason`); everywhere else it
    # stays False, so a backend that simply doesn't report finish reasons can never be
    # mistaken for a cut connection. Usage is NOT a substitute signal here: plenty of
    # compat endpoints ignore `stream_options.include_usage` on a perfectly good stream.
    truncated: bool = False

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True)
class ModelCapabilities:
    """What a given model/provider can do; used for graceful degradation."""

    tools: bool = True
    vision: bool = False
    # Native PDF ingestion (OpenAI `file` part / Anthropic document / Gemini inline_data).
    # Models without it get a local fallback: text extraction or page images (pdf_support.py).
    pdf: bool = False
    parallel_tool_calls: bool = True
    streaming: bool = True


@dataclass
class StreamChunk:
    """One streamed piece: a text and/or reasoning delta, and/or (final) the full turn."""

    text_delta: Optional[str] = None
    reasoning_delta: Optional[str] = None
    turn: Optional[AssistantTurn] = None


class ProviderClient(ABC):
    """Single-shot, provider-agnostic completion interface.

    Deliberately blocking (the turn engine wraps it in `asyncio.to_thread`) and
    deliberately without a `max_turns` loop — the runtime owns the agent loop.
    """

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        """Return one assistant turn for the given messages/tools."""

    @abstractmethod
    def capabilities(self, model: str) -> ModelCapabilities:
        """Return capability flags for the given model."""

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        """Yield StreamChunks. Default: no token streaming — one final chunk with the
        full turn. Providers that support streaming (OpenAIProvider) override this."""
        yield StreamChunk(
            turn=self.complete(model=model, messages=messages, tools=tools, **settings)
        )
