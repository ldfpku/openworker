"""TurnEngine — the owned agent loop.

Async, but with blocking provider/tool calls wrapped in `asyncio.to_thread` so the loop
(and any UI consuming its events) stays responsive. One user turn spans many model↔tool
iterations until the model stops requesting tools, a rail trips, or it's interrupted.
When the model requests several tool calls in one turn, low-risk ones (reads, searches)
execute concurrently; writes/shell stay strictly ordered.

Approvals are handled out-of-band via an injected async `approver`: when the permission
engine says `needs_user`, the engine emits `PERMISSION_REQUIRED` and awaits the approver.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from . import compaction as _compaction
from . import provenance
from . import session_facts
from . import toolchain as _toolchain
from .events import Event, EventType

# §8.4 retry guard: the reviewer pauses for the rest of the turn after this many denials
# IN A ROW (2→5 + streak semantics, owner ruling 2026-08-24 — a cumulative 2 silently
# downgraded long agentic turns to hand-approval after one over-strict pair).
_REVIEWER_TRIP = 5
_REVIEWER_PAUSED_TEXT = (
    "Auto-approve is paused for the rest of this turn — the reviewer blocked "
    f"{_REVIEWER_TRIP} actions in a row, so approvals now come to you."
)
from .permissions import Mode, PermissionEngine
from .providers import AssistantTurn, ProviderClient, ToolCall
from .providers.base import SYSTEM_CONTEXT_OPEN
from .providers.errors import (
    friendly_model_error,
    is_transient_model_error,
    retry_after_seconds,
)
from .providers.openai_provider import looks_like_unparsed_tool_call
from .risk import RiskClass, classify
from .taskutil import spawn_retained
from .tools import ToolRegistry

logger = logging.getLogger("coworker.engine")

# Finish/stop reasons that mean "the model ran out of output budget". Every provider
# normalizes to the OpenAI vocabulary before the turn reaches here (anthropic/bedrock
# `max_tokens`, gemini `MAX_TOKENS`, responses `max_output_tokens` all map to "length"),
# so "length" is the value in practice; the raw spellings stay in the set as a guard for
# compat endpoints whose own value passes through unmapped.
_LENGTH_FINISH_REASONS = frozenset(
    {"length", "max_tokens", "max_output_tokens", "model_length"}
)
# Finish reasons that mean "something refused to let this through" — a safety filter, a
# guardrail, a recitation/blocklist hit. Every provider normalizes its own spelling to
# `content_filter` (anthropic `refusal`, bedrock `guardrail_intervened`/`content_filtered`,
# gemini `SAFETY`/`RECITATION`/…, responses `incomplete_details.reason`), because the
# engine has to tell this apart from a plain empty answer: one is worth re-running and the
# other returns the identical block however many times it is asked.
_FILTERED_FINISH_REASONS = frozenset({"content_filter", "content_filtered", "safety"})

# Why a turn ended with nothing to show, in the order the checks run. Server-authored
# English, persisted verbatim on the notice (like every other marker) and localized at
# display time from the structured `reason` — see surfaces/gui/src/modeNotice.ts.
_TURN_ABORTED_TEXT = {
    "no_finish": (
        "The model's response was cut off before it finished (no end-of-stream from the "
        "provider). Nothing was answered or done."
    ),
    "length": "The model hit its output length limit before producing an answer.",
    # Deliberately wider than "safety": the same class carries recitation and blocklist
    # hits, which are content policy but not safety.
    "filtered": "The provider blocked this response under its content policy.",
    "empty": "The model returned an empty response.",
}
# Same, for a turn that DID answer but was cut off part-way: the text is already on
# screen, so this is a warning appended after it, not a failure.
_TURN_TRUNCATED_TEXT = {
    "no_finish": (
        "The response may be incomplete: it was cut off before the provider signalled the "
        "end of the stream."
    ),
    "length": "The response may be incomplete: the model hit its output length limit.",
}
# Notice kinds `retry()` will re-run. An aborted turn is exactly as retriable as a
# provider failure — nothing was answered and nothing was done.
_RETRIABLE_NOTICE_KINDS = frozenset({"error", "turn_aborted"})
# Notice kinds the retry guard looks THROUGH when it searches for that tail: bookkeeping
# written after a turn failed that says nothing about the failed turn itself.
# - `model_switch`: switching models and THEN retrying is the intended recovery path.
# - `answer_superseded` (manager `_note_superseded_answer`): an Inbox answer came in after
#   the conversation had moved past its prompt, so nothing ran for it. It is appended
#   whenever that answer arrives, which can be right after an error notice (the turn that
#   moved past the prompt failed, or the resume's own continuation did); counted as a
#   tail, it took the Retry away from that failure.
# The GUI's `retryAnchor` (Transcript.tsx) must agree, or the Retry button and this guard
# disagree about the same transcript: it looks through `retryTransparent` items, which
# `answerSupersededNotice` sets, and through `info` notices, which model switches are.
_RETRY_TRANSPARENT_NOTICE_KINDS = frozenset({"model_switch", "answer_superseded"})

# -- automatic retry of a model call that delivered nothing --------------------------
#
# A severed stream is not a decision the model made, it is a call that never landed, and
# making the user click Retry for it is making them do the machine's job. Bounded, and
# only for round-trips that delivered NOTHING: a turn with text in it is never re-run,
# because the user has already read that text and a second answer would duplicate it.
_MODEL_RETRIES_ENV = "OPENWORKER_MODEL_RETRIES"
_MODEL_RETRIES_DEFAULT = 2
# An attempt that ran this long before dying is expensive to repeat — the 2026-09-18
# incident thought for 232 seconds and then dropped, so the default budget would have
# spent twelve more minutes and three times the tokens to reach the same sentence. Past
# this mark one retry is all it gets.
_LONG_ATTEMPT_ENV = "OPENWORKER_MODEL_RETRY_LONG_ATTEMPT_SECONDS"
_LONG_ATTEMPT_DEFAULT = 90.0
_LONG_ATTEMPT_RETRIES = 1
# Waits before attempt 2 and attempt 3, in seconds, each ±_RETRY_JITTER. Long enough for a
# busy backend to drain, short enough that the user reads it as "retrying" and not a hang.
_RETRY_BACKOFF = (2.0, 6.0)
_RETRY_JITTER = 0.25
# A vendor's own Retry-After is honoured, but never past this: a five-minute hint would
# strand the user in front of a spinner with no way to tell it from a hang.
_RETRY_AFTER_CAP = 30.0
# Automatic retries allowed across the WHOLE user turn, every round together. Without it a
# tool-heavy turn could pay the per-call budget again on each of fifty rounds.
_TURN_RETRY_CAP = 4
# Which failures earn a re-run. "length" does not (the same prompt meets the same ceiling)
# and neither does "filtered" (a block is a decision, not an accident) — retrying either
# only spends the budget to arrive at the identical sentence.
_RETRIABLE_ABORT_REASONS = frozenset({"no_finish", "empty"})
# Per-reason ceilings ON TOP of the configured budget. A bare empty answer is the weakest
# evidence of a transport problem there is — it can just as easily be a model that had
# nothing to say — so it gets one courtesy re-run, not the full budget.
_REASON_RETRY_CAP = {"empty": 1}
# Server-authored English, persisted on the `turn_retry` marker and localized at display
# time from the structured reason/attempt/max (surfaces/gui/src/modeNotice.ts).
_TURN_RETRY_TEXT = {
    "no_finish": "The model's response was cut off; retrying ({attempt}/{max})…",
    "empty": "The model returned an empty response; retrying ({attempt}/{max})…",
    "transient": "The model call failed; retrying ({attempt}/{max})…",
}
# Appended to the give-up sentence so the user knows the machine already tried.
_TURN_ABORTED_RETRIED = " Automatic retry didn't help ({n} retries)."

# -- the first-chunk deadline --------------------------------------------------------
#
# A provider that ACCEPTS the request and then sends nothing is the one stall the bridge
# had no answer for: the Stop race below covers the user changing their mind, but nothing
# covered the user simply waiting. The agent loop deliberately passes no `timeout`, so
# each vendor SDK's own defaults are all that ever ends such a call (`base.bounded_client`
# says as much: "the agent loop wants the SDK's own resilience"). What those defaults are
# was READ OFF THE SDKs installed in this repo's venv on 2026-09-22 — no live provider was
# stalled, and none of this comes from a production incident:
#
#   * OpenAI and Anthropic: `openai._constants.DEFAULT_TIMEOUT` and the anthropic
#     equivalent are both `Timeout(connect=5.0, read=600, write=600, pool=600)`, with
#     `DEFAULT_MAX_RETRIES = 2` and a timed-out request counted as retryable. ~1800s worst
#     case, by the same multiplier `bounded_client` exists to defeat. (openai 3.3.1,
#     anthropic 1.2.0.)
#   * Bedrock: `bedrock_provider._ensure_client` builds the boto3 client with no
#     `botocore.config.Config`, so botocore's default `read_timeout` — 60s, read off
#     `botocore.config.Config().read_timeout` — is what applies. How many attempts
#     botocore stacks on top of that was NOT derived here.
#   * Gemini: `gemini_provider` passes `types.HttpOptions(base_url=…, headers=…)` and no
#     `timeout` at all, so whatever google-genai defaults to is the only bound. The
#     scoping run for this change called that unbounded; this comment does not re-derive
#     it, so treat "unbounded" as that run's figure, not as measured here.
#
# So "eventually" is between ten minutes and never, and until then the turn shows a
# spinner and the server log shows nothing at all.
#
# This bounds the WAIT, not the resources. When it fires the producer thread is still
# parked in the provider's read and the socket is still open; both are let go only when
# that read finally returns on the numbers above — and NOTHING IN THIS TREE SHORTENS THAT.
# The commit that introduced this deadline claimed Gemini's unbounded read was covered by
# a 600s backstop "on another branch"; that branch is not in this repository (checked
# 2026-09-22: `git ls-remote --heads origin` lists only `refs/heads/main`, and grepping
# `coworker/providers/gemini_provider.py` for `timeout` returns nothing), so a wedged
# Gemini call parks its producer thread for as long as the SDK lets it, exactly as before.
# The gain claimed here is therefore exactly one thing: the user (and the automatic retry)
# stops waiting on a wedged call.
_FIRST_CHUNK_TIMEOUT_ENV = "OPENWORKER_FIRST_CHUNK_TIMEOUT"
_FIRST_CHUNK_TIMEOUT_DEFAULT = 120.0
# Spellings that mean "no deadline at all" — for a self-hosted endpoint whose queue really
# can hold a request for many minutes before the first token.
_FIRST_CHUNK_TIMEOUT_OFF = frozenset({"off", "none", "never"})
# Logged when a first chunk DID arrive, but took more than this share of the deadline.
# Data for a later decision about a between-chunks deadline; it changes no behaviour.
_SLOW_FIRST_CHUNK_FRACTION = 0.5


# -- Stop that does not wait for the tool --------------------------------------------
#
# Stop cannot reach into a running tool thread: `asyncio.to_thread` has no cancellation
# and `task.cancel()` only frees the awaiter. Measured on this repo 2026-09-22 (scratchpad
# probes, since deleted) with a tool that sleeps 3s: pressing Stop ended the turn 2.695s
# later on the serial path and 2.693s later on the parallel path — i.e. after exactly the
# tool's remaining runtime. Where the discarded result is the entire loss (see
# `TurnEngine._abandonable`) the turn stops WAITING instead, and the thread finishes into
# a log line.
#
# `auto` (the default) abandons the classified-safe set, `all` abandons every tool, `none`
# restores the pre-2026-09-22 behaviour of always waiting. Anything else reads as `auto`.
_ABANDON_ENV = "OPENWORKER_STOP_ABANDONS_TOOLS"
_ABANDON_MODES = frozenset({"auto", "all", "none"})
_ABANDON_DEFAULT = "auto"
# Read-only network tools. They classify EGRESS because the MODEL picks the destination
# and the URL/query can carry data off-machine — that is the permission gate's concern,
# not this one. Neither changes anything at the far end, so discarding the response loses
# the response and nothing else.
_ABANDONABLE_EGRESS_TOOLS = frozenset({"web_fetch", "web_search"})
# Tools that already stop themselves, and come back with a truthful result when they do.
# Abandoning one would win the race against its own stop path and replace that result with
# "unavailable". `explore` relays the parent's Stop into its child engine (tools/subagent.py
# + agent.py, landed 2026-09-19) and returns its partial report; MCP calls are cancelled by
# the hook in coworker/mcp/tools.py — those are matched by category, not by name.
# `run_shell` belongs to the same family (agent.py's standing `executor.interrupt_now`
# hook) but needs no entry here: it classifies EXEC and never reaches this set.
_SELF_INTERRUPTING_TOOLS = frozenset({"explore"})
# READ-classified tools that nevertheless change state outliving the turn. `RiskClass.READ`
# is a FALLBACK in risk.py — not in the by-name table and no `requires_approval` means READ
# — so it is not a proof of purity and the abandon set cannot be left to it alone. These
# were found by classifying every tool the `cowork` persona registers, deferred sets
# materialised (2026-09-22, scratchpad probe, since deleted):
#   load_skill       mounts the skill's own folder as a read-only root on the session's
#                    SHARED roots list (skills/base.py `_mount`), widening what the session
#                    may read — and unlike the other two it can genuinely be slow enough to
#                    be abandoned, because a catalog miss walks the disk
#                    (`loader.rescan(force=True)` plus `_bundled_files`).
#   shell_task_output  a DESTRUCTIVE read: `_BackgroundTask.read_new` returns the lines
#                    since the last call and advances the cursor past them
#                    (tools/shell.py), so abandoning does not merely discard the result —
#                    that slice of the background task's output is gone for good and no
#                    later call can fetch it. The one member for which discarding the
#                    result is demonstrably NOT the whole loss.
#   todo_write       rewrites the session's todo list.
#   shell_task_kill  kills a background shell task.
# Each is microseconds-to-milliseconds except `load_skill` on a cold catalog, so waiting
# them out costs Stop essentially nothing — which is the trade this set makes.
_SIDE_EFFECTING_READS = frozenset(
    {"load_skill", "shell_task_output", "todo_write", "shell_task_kill"}
)
# The on-demand tool loaders (`load_github_tools`, …) are the same case, excluded by
# CATEGORY because their names vary with which connectors are configured. Each mutates
# `ToolRegistry._tools` (tools/deferred.py `_load` → `register_all`), which the loop reads
# unlocked every round trip in `registry.schemas()`; before this change no tool thread
# could outlive its turn, so the two could not overlap, and abandoning is precisely what
# would remove that guarantee.
_SIDE_EFFECTING_READ_CATEGORY = "meta"
# Process-wide, because the thread pool they occupy is process-wide.
_abandoned_lock = threading.Lock()
_abandoned_live = 0
_abandoned_warned = False


def _abandon_mode() -> str:
    raw = (os.environ.get(_ABANDON_ENV) or "").strip().lower()
    return raw if raw in _ABANDON_MODES else _ABANDON_DEFAULT


def _abandoned_outcome(fut: "asyncio.Future") -> str:
    """One short phrase saying how an abandoned tool thread ended, for the log line and
    the audit record — never its result, which is thrown away unread.

    A tool that blows up after the stop does NOT surface here as an exception:
    `_execute_sync` catches every `Exception` and turns it into an `(error dict, "error")`
    outcome, so the phrase names the status and the `error_type` it carried. The raised
    branch is for what `_execute_sync` does not catch (a `BaseException` out of the
    thread) and for the task being cancelled out from under the callback.
    """
    if fut.cancelled():
        return "cancelled"
    exc = fut.exception()
    if exc is not None:
        return f"raised {type(exc).__name__}: {exc}"
    try:
        result, status = fut.result()
    except Exception as unpack:  # pragma: no cover - `_execute_sync` always returns a pair
        return f"unreadable outcome: {type(unpack).__name__}"
    kind = result.get("error_type") if isinstance(result, dict) else None
    return f"status={status}" + (f", {kind}" if kind else "")


def _default_thread_pool_size() -> int:
    """How many threads `asyncio.to_thread` can use at once — CPython's default
    `ThreadPoolExecutor` sizing, which the loop's default executor takes. Only used to
    size the "too many abandoned threads" warning, so an inexact answer is harmless."""
    return min(32, (os.cpu_count() or 1) + 4)


def _model_retries() -> int:
    """How many times one dead model call is re-run automatically. Garbage falls back to
    the default; an explicit 0 IS honoured — unlike a timeout, "none" is a sane setting
    here, it just means "ask me". Clamped to the per-turn cap, because a budget bigger
    than the turn's total can never be spent and would only lie in the "(1/9)" counter."""
    raw = (os.environ.get(_MODEL_RETRIES_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return _MODEL_RETRIES_DEFAULT
        if value >= 0:
            return min(value, _TURN_RETRY_CAP)
    return _MODEL_RETRIES_DEFAULT


def _long_attempt_seconds() -> float:
    """How long a dying attempt has to run before it's only worth repeating once."""
    raw = (os.environ.get(_LONG_ATTEMPT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _LONG_ATTEMPT_DEFAULT
        if value > 0:
            return value
    return _LONG_ATTEMPT_DEFAULT


def _first_chunk_timeout() -> Optional[float]:
    """Seconds a stream may deliver nothing at all before it counts as wedged, or None
    for no deadline.

    Garbage, 0 and negatives fall back to the default — the same rule `_oneshot_timeout`
    uses (server/manager.py) and deliberately NOT the rule `_model_retries` uses: there,
    "0" is a meaningful answer ("ask me instead of retrying"), here "wait forever" is the
    failure this exists to prevent, so it has to be spelled out rather than fallen into.
    `off`/`none`/`never` (any case) is that explicit spelling.
    """
    raw = (os.environ.get(_FIRST_CHUNK_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _FIRST_CHUNK_TIMEOUT_DEFAULT
    if raw.lower() in _FIRST_CHUNK_TIMEOUT_OFF:
        return None
    try:
        value = float(raw)
    except ValueError:
        return _FIRST_CHUNK_TIMEOUT_DEFAULT
    if value > 0:
        return value
    return _FIRST_CHUNK_TIMEOUT_DEFAULT


def _retry_delay(attempt: int, retry_after: Optional[float] = None) -> float:
    """Seconds to wait before the 1-based `attempt`. A vendor's own Retry-After wins over
    the schedule (it knows when its queue drains), capped; otherwise fixed backoff with a
    little jitter so several sessions recovering at once don't re-collide. A non-positive
    hint is NOT honoured — "retry immediately" against a backend that just refused us is
    how a bounded retry turns into a hot loop — so it falls back to the schedule too."""
    if retry_after is not None and retry_after > 0:
        return min(retry_after, _RETRY_AFTER_CAP)
    base = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)) - 1]
    return base * (1.0 + random.uniform(-_RETRY_JITTER, _RETRY_JITTER))


def _is_length_finish(finish_reason: Optional[str]) -> bool:
    return (finish_reason or "").strip().lower() in _LENGTH_FINISH_REASONS


def _is_filtered_finish(finish_reason: Optional[str]) -> bool:
    return (finish_reason or "").strip().lower() in _FILTERED_FINISH_REASONS


def _abort_reason(turn: AssistantTurn, *, trust_truncated: bool) -> str:
    """Why an answerless turn produced nothing — `_TURN_ABORTED_TEXT`'s key.

    The explicit signals win, most specific first: a block is a decision, a length limit
    names its own cause. `no_finish` comes last and is doubly gated — on `turn.truncated`
    (only a provider that can tell a severed stream from a clean one sets it, see
    providers/base.py) AND on `trust_truncated`, the engine's own observation that THIS
    model has actually been seen reporting a finish reason in this session. Without the
    second gate, a compat endpoint that never sends the field would have every one of its
    perfectly good replies accused of being cut short."""
    if _is_filtered_finish(turn.finish_reason):
        return "filtered"
    if _is_length_finish(turn.finish_reason):
        return "length"
    if turn.truncated and trust_truncated:
        return "no_finish"
    return "empty"


class ApprovalOutcome(str, Enum):
    ONCE = "once"
    ALWAYS_TOOL = "always_tool"
    ALWAYS_COMMAND = "always_command"
    ALWAYS_DOMAIN = "always_domain"
    # Session-wide grant for classifier-approved read-only shell commands (readonly.py).
    READONLY_SESSION = "readonly_session"
    DENY = "deny"


def _readonly_ok(arguments: dict) -> bool:
    command = str((arguments or {}).get("command", "") or "")
    if not command:
        return False
    from .readonly import is_readonly_command

    return is_readonly_command(command)


@dataclass
class PermissionRequest:
    tool_name: str
    arguments: dict[str, Any]
    metadata: Any
    reason: str
    tool_call_id: Optional[str] = None  # for durable resume (idempotent inbox item)


Approver = Callable[[PermissionRequest], Awaitable[ApprovalOutcome]]


async def _deny_all(_request: PermissionRequest) -> ApprovalOutcome:
    return ApprovalOutcome.DENY


class StreamBridgeError(RuntimeError):
    """The provider stream's thread bridge ended for a reason that isn't an answer.

    `_astream` raises it on exactly one outcome, and the wording is deliberate about which:
    the Stop wait WOKE — so the flag had been set — the queue delivered nothing, and by
    the time the bridge reads the flag back it is clear again. Nothing but `clear()` can do
    that, and only `run`/`retry`/`resume` call it, each as the first act of a turn. So this
    is what "a second turn was started on this engine while an older stream was still live"
    looks like from inside the bridge: the new turn wipes the Stop the user pressed, and the
    older stream is left holding a wake-up that no longer stands for anything. Not "never
    expected", then — expected precisely when the one-turn-per-engine claim leaks. The
    WebSocket receive loop claims the session before it schedules a turn, and every
    background turn (scheduled tasks, team delivery, self-wake, durable resume) has to
    claim it too; one of those was found not doing so on 2026-09-18/19.

    What it is NOT is the ordinary Stop, which leaves the flag set and returns quietly two
    lines above. And it exists at all so the bridge can never again end a stream QUIETLY
    for a reason it cannot name: a silent return there reaches the user as an assistant
    turn that simply came back empty, with nothing in the events or the log to say why
    (2026-09-18).

    Upstream it is handled as an ordinary provider failure — `_loop`'s `except Exception`
    around `_astream` reads it as neither a context overflow nor transient, so whatever text
    had already streamed is persisted, an `error` notice is appended (which keeps Retry on
    offer) and the turn ends on `EventType.ERROR` carrying `error_type="StreamBridgeError"`
    and this message as its text.
    """


class FirstChunkTimeout(TimeoutError):
    """The provider accepted the request and then sent nothing for `first_chunk_timeout`.

    Raised by `_astream` only while the stream is still empty. The clock starts when the
    producer thread gets its slot in the executor (not when `_astream` does, which would
    time the pool's own backlog) and stops at the first chunk of any kind, thinking text
    included. Nothing bounds the gaps BETWEEN chunks; a stream that has started and then
    stalls still hangs exactly as before.

    It subclasses `TimeoutError` on purpose, and that is the whole integration: the
    isinstance arm of `providers/errors.is_transient_model_error` matches `TimeoutError`,
    so the bounded automatic retry added in v0.6.5 picks this up with no change to the
    retry code, to the `turn_retry` reasons, or to the GUI's localized sentences — it
    arrives as an ordinary `reason="transient"` failure. (Verified by test, not assumed:
    `test_a_first_chunk_timeout_is_transient_to_the_retry_gate`.)

    What it is NOT is a resource bound. When it is raised the producer thread is still
    inside the provider's read and the socket is still open; both are released only when
    that read returns on the HTTP layer's own schedule (see `_FIRST_CHUNK_TIMEOUT_ENV`).
    So an engine that gives up here and retries can be holding two sockets, and a turn
    that fails here leaves one behind for as long as the vendor SDK takes. No provider's
    STREAM path in this tree narrows that: the one per-request timeout any of them sets
    (`anthropic_provider._nonstreaming_timeout`) is applied to `complete` only and says so
    itself; `gemini_provider` sets none anywhere.

    And it is not only a socket. A parked producer also holds one worker of the loop's
    DEFAULT executor, which is what `asyncio.to_thread` uses too — so the same pool
    `_handle_tool_calls` and every `to_thread` under `server/` draw from, sized
    `min(32, cpu_count + 4)` (read off CPython 3.13's `ThreadPoolExecutor.__init__`,
    `BaseEventLoop.run_in_executor` and `asyncio.to_thread`). The automatic retry doubles
    that hold per wedged turn. Enough wedged turns at once would therefore starve thread
    work elsewhere in the process, not just this engine — that consequence is INFERRED
    from those three sources, not measured.

    One inherited behaviour, unchanged and worth knowing: `explore` builds a subagent
    TurnEngine of its own (tools/subagent.py), which picks this up along with its own
    `model_retries`. A wedged subagent call is therefore retried inside that engine first,
    and the parent turn waits for the whole of it. That is what every other transient
    failure already does there; this adds a new way in, not a new rule.
    """


def _wake(future: asyncio.Future) -> None:
    if not future.done():
        future.set_result(True)


class _StopSignal:
    """The turn's Stop flag: `asyncio.Event`'s surface without its event-loop binding.

    `asyncio.Event` binds itself to the first loop that awaits it and raises on every loop
    after that (`asyncio.mixins._LoopBoundMixin`). No production path drives one engine
    across two event loops today — `explore` builds a fresh subagent engine per call and
    runs it on exactly one event loop of its own (tools/subagent.py) — but staying
    loop-agnostic here is defensive: it's what keeps tests, the CLI, and any future code
    that reuses one engine across separate `asyncio.run` calls from ever landing on
    "bound to a different loop", and it lets `set()` be called safely from any thread —
    which matters because Stop is also set from threads that have no loop at all (the
    manager cancelling a team run, deleting a session). So the flag keeps its own
    registry of waiters, one per loop, instead of belonging to one of them. A Stop also
    travels from a thread running a DIFFERENT loop: the session's Stop is relayed into the
    `explore` subagent's engine, which waits on its own loop in a worker thread.

    Supports exactly what the engine uses: `set`, `clear`, `is_set`, and an awaitable
    `wait`. `is_set` is a plain attribute read, which is what makes it safe to poll from
    the producer thread.
    """

    def __init__(self) -> None:
        self._flag = False
        # Guards "check the flag, then register" against "set the flag, then take the
        # waiters", which is the only ordering that can drop a wake-up.
        self._lock = threading.Lock()
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = []

    def is_set(self) -> bool:
        return self._flag

    def clear(self) -> None:
        self._flag = False

    def set(self) -> None:
        with self._lock:
            if self._flag:
                return
            self._flag = True
            waiters, self._waiters = self._waiters, []
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None  # called from a thread with no loop of its own
        # Resolved outside the lock: a waiter's own `finally` re-enters to deregister.
        for loop, future in waiters:
            if loop is running:
                # Same loop, same thread — resolve inline, exactly as `asyncio.Event.set()`
                # does, so a Stop doesn't arrive an event-loop turn later than it used to.
                _wake(future)
                continue
            try:
                loop.call_soon_threadsafe(_wake, future)
            except RuntimeError:
                pass  # that loop is closed; nobody is left there to wake

    async def wait(self) -> bool:
        if self._flag:
            return True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._lock:
            if self._flag:  # set() landed between the read above and the lock
                return True
            self._waiters.append((loop, future))
        try:
            return await future
        finally:
            # Cancelled, failed or woken, the registration goes: the bridge starts a fresh
            # wait for every chunk, so a waiter that outlived its own task would pile up
            # for the length of the answer.
            with self._lock:
                for index, (_loop, registered) in enumerate(self._waiters):
                    if registered is future:
                        del self._waiters[index]
                        break


class TurnEngine:
    def __init__(
        self,
        *,
        provider: ProviderClient,
        registry: ToolRegistry,
        permissions: PermissionEngine,
        model: str,
        instructions: Optional[str] = None,
        approver: Optional[Approver] = None,
        max_iterations: int = 12,
        # Second gate on a runaway turn, in the unit the bill is actually denominated in.
        # `max_iterations` counts ROUNDS: it cannot tell a turn that read four small files
        # from one that read four 40k-line logs, so it stops the cheap turn and the
        # expensive one at the same place. 0 disables. See `_loop`.
        max_turn_tokens: int = 0,
        model_settings: Optional[dict[str, Any]] = None,
        messages: Optional[list[dict[str, Any]]] = None,
        audit_sink: Optional[Callable[[dict[str, Any]], None]] = None,
        context_provider: Optional[Callable[[], str]] = None,
        directory_requester: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        plan_approver: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        question_asker: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        tool_requester: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        team_approver: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        items_approver: Optional[
            Callable[[dict[str, Any]], "Awaitable[dict[str, Any]]"]
        ] = None,
        # Called (thread-safe, best-effort) when the user stops the turn — e.g. the
        # executor's kill for a running shell command.
        interrupt_hooks: Optional[list[Callable[[], None]]] = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.permissions = permissions
        self.model = model
        self.approver = approver or _deny_all
        self.max_iterations = max_iterations
        self.max_turn_tokens = max_turn_tokens
        self.model_settings = dict(model_settings or {})
        self.messages: list[dict[str, Any]] = list(messages or [])
        self.audit_sink = audit_sink
        # Returns an ephemeral `<system-context>` block appended as an INDEPENDENT trailing
        # user message at send-time only (never persisted). We can't reliably inject system
        # messages mid-thread across providers, so dynamic per-turn context (e.g. the live
        # directory list) rides as its own tail message rather than being glued onto the
        # latest user turn — gluing it on would change that message's bytes every turn and
        # invalidate provider-side prompt caching of the conversation prefix. Returns "" when
        # there's nothing to add.
        self.context_provider = context_provider
        # Handles the `request_directory` tool: emits a DIRECTORY_REQUESTED prompt, waits for the
        # user to grant/decline a folder out-of-band, applies the grant to this live session, and
        # returns the outcome. None on surfaces that can't prompt (the tool then no-ops).
        self.directory_requester = directory_requester
        # Handles the `request_tool` tool: emits TOOL_REQUESTED, waits for the user to install
        # the pinned build or decline. None on surfaces that can't prompt (the tool then
        # no-ops, and the agent is told so it can fall back openly rather than skip silently).
        self.tool_requester = tool_requester
        # Handles the `propose_plan` tool: emits PLAN_PROPOSED, waits for the user's decision.
        # An approving result flips the live PermissionEngine out of plan mode (same session,
        # context kept). None on surfaces that can't prompt (the tool then no-ops).
        self.plan_approver = plan_approver
        # Handles the `propose_team` tool (the staffing gate): emits TEAM_PROPOSED, waits
        # for the user's decision; approval pre-spawns the worker sessions and the result
        # carries the roster (actor ids). None on surfaces that can't prompt.
        self.team_approver = team_approver
        # Handles `propose_work_items` (the decomposition gate): emits ITEMS_PROPOSED,
        # waits; approval creates the items on the board. Mode-independent by design —
        # unlike propose_plan it carries no permission-mode semantics: propose_plan is
        # an IMPLEMENTATION plan (steps/files, plan-mode exit); this is a team
        # decomposition onto the board.
        self.items_approver = items_approver
        # Handles the `ask_user` tool: turns a question into an Inbox item and waits for the answer
        # (answerable inline in a live session or from the Inbox when unattended). None on surfaces
        # that can't ask (the tool then no-ops).
        self.question_asker = question_asker
        # Auto-compaction (OPE-27) — set post-construction by the surface/manager so the
        # constructor footprint stays put. `compaction_settings` is a live getter (Settings
        # changes apply without a rebuild); `is_attended` gates the failure prompt (None →
        # treat as unattended: never park a background run on internal bookkeeping).
        self.compaction_state: Optional[_compaction.CompactionState] = None
        self.compaction_settings: Optional[Callable[[], dict[str, Any]]] = None
        self.is_attended: Optional[Callable[[], bool]] = None
        # Session facts (spec Part 0 / §2.4) — the known world frozen at session start, plus
        # the per-turn ingestion record. Set post-construction by the surface, same as
        # compaction above, so the constructor footprint stays put. None ⇒ nothing recorded
        # and behaviour is byte-identical; NOTHING consumes it in v1 either way.
        self.session_facts: Optional[session_facts.SessionFacts] = None
        # Auto-Approve reviewer (spec Part 8). Set post-construction; None ⇒ Mode.AUTO_APPROVE
        # behaves exactly like INTERACTIVE. Consulted only on decisions the gate marked
        # needs_user, only in AUTO_APPROVE mode, only when the session is attended (an
        # unset is_attended counts as NOT attended here — automations never set it), and
        # only until _REVIEWER_TRIP denials IN A ROW (§8.4 retry guard). Consecutive, not
        # cumulative: an allow/unsure verdict or an ask_user answer resets the streak —
        # the owner-hit 2026-08-24 was a 2-denial cumulative trip silently downgrading a
        # long agentic turn to hand-approval for everything after one over-strict pair.
        self.reviewer: Optional[Any] = None
        self._reviewer_denials = 0
        self._reviewer_verdicts: dict[str, Any] = {}
        # (c) How each consequential call got cleared, keyed by tool_call id:
        # {"origin": "reviewer"|"bypass"|"user", "note": <reviewer reasoning>, "grant":
        # <user outcome>}. Consumed by _record_result into the TOOL_FINISHED event AND
        # into the tool message's `_display` sidecar, so the quiet provenance chips
        # survive reload (owner ruling 2026-08-24) — display-only, never provider-visible.
        self._approval_origins: dict[str, dict[str, str]] = {}
        # When each call actually STARTED running, keyed by tool_call id — not when the
        # model asked for it. The assistant message is appended (and checkpointed) before
        # authorization, so its `ts` can precede execution by however long the human took
        # at the approval card. Consumed by `_record_result` into the result message's `t0`
        # sidecar, which is what tells the Artifacts panel which files a shell command
        # could plausibly have written (SessionManager._shell_windows).
        self._tool_started_at: dict[str, float] = {}
        # Shadow evaluation (spec Part 6 step 3): when True and a reviewer is attached, the
        # reviewer records what it WOULD have decided on each approval card while the human
        # still decides. Fire-and-forget — the card is never delayed, no decision is ever
        # touched, and the verdict lands in the audit log (stage="reviewer_shadow", joined
        # to the human's approval_resolved row by call_id).
        self.reviewer_shadow = False
        self._shadow_tasks: set[asyncio.Task] = set()
        # One-shot "Allow anyway" grants (§8.4): minted ONLY by a human clicking the deny
        # card, keyed on the exact tool + canonical arguments, consumed on first match. A
        # re-proposal with even slightly different arguments does not match and goes back
        # through the reviewer/card — deliberately narrow, deliberately not standing.
        self._allow_anyway: set[tuple[str, str]] = set()
        # ask_user answers for the reviewer's history (§8.2 — the missing third of the
        # reply-tag feature: render_history prints the tag and the §8.3 instructions say to
        # weigh it lower; this is the extractor that finally delivers the data). Captured at
        # the moment the asker returns — the one point where the engine KNOWS the text came
        # from the human, whichever authenticated surface answered (inline card, Inbox, or a
        # bound channel; the same trust approval clicks already carry). ANSWERS ONLY, never
        # the agent's question: agent-authored text stays out of the judge's view — showing
        # the question too is step 2, evidence-gated on shadow data. Each entry is
        # (anchor, text) where anchor = how many user messages existed at capture, so the
        # merge in `_user_history` stays chronological. Runtime-only on purpose: a restart
        # costs the reviewer context (more cards), never correctness.
        self._ask_replies: list[tuple[int, str, str]] = []  # (anchor, answer, question)
        # Extra user-facing fields for a tool's approval card, merged into the
        # PERMISSION_REQUIRED payload — e.g. web_search's live provider name, so the card
        # can say where queries actually go (§1.9). Set post-construction by the surface
        # (the engine itself knows nothing about providers); None ⇒ no extras. Called at
        # card time, not session start, so a mid-session Settings change shows through.
        self.approval_extras: Optional[
            Callable[[str, dict[str, Any]], dict[str, Any]]
        ] = None
        # What the agent itself created this session (OPE-114 §1). The reviewer never sees
        # file contents, so `python scripts/setup.py` is unjudgeable from its text — but the
        # engine knows whether it wrote or downloaded that file moments ago, and says so on
        # the card and in the reviewer's request. Runtime-only, like `_ask_replies`: a
        # restart costs context (more cards), never correctness.
        self._agent_files = provenance.SessionFiles(permissions.workspace_root)
        # Completed tool calls so far, so a fact can say how many steps back the write was.
        self._step = 0
        self._last_context_tokens: Optional[int] = None
        self.audit_context: dict[str, Any] = {}
        if instructions and not (
            self.messages and self.messages[0].get("role") == "system"
        ):
            self.messages.insert(0, {"role": "system", "content": instructions})
        self._cancel = _StopSignal()
        # Whether the latest assistant turn hit the output-token limit — decides which
        # diagnosis a mangled (unparseable-args) tool call gets answered with.
        self._turn_truncated = False
        # Automatic retry of a model call that delivered nothing. `retry_sleep` is the
        # seam tests replace so a backoff never really waits; the default IS a wait on the
        # cancel event, which is what makes Stop bite DURING the pause and not after it.
        # `clock` is the matching seam for "how long did the dead attempt run".
        self.model_retries = _model_retries()
        # How long `_astream` waits for the FIRST chunk before calling the connection
        # wedged (None = no deadline). Read once here so a test can set the attribute
        # instead of the environment; see `FirstChunkTimeout`.
        self.first_chunk_timeout: Optional[float] = _first_chunk_timeout()
        self.retry_sleep: Callable[[float], Awaitable[bool]] = self._sleep_unless_stopped
        self.clock: Callable[[], float] = time.monotonic
        # Model ids seen reporting a finish reason at least once. A backend that simply
        # never sends the field must not have its ordinary replies read as severed
        # streams, and the only honest way to know which kind it is, is to watch it —
        # keyed by model id so a mid-session switch starts the observation over. Re-seeded
        # from the loaded history below: the `finish_reason` sidecar is persisted, so a
        # resumed session (or a restart, or an evicted-and-rebuilt engine) knows what it
        # already learned instead of spending its first real cut-off saying "empty".
        self._finish_reason_seen: set[str] = _models_that_report_finish(
            self.messages, self.model
        )
        # Each pending steering message: (text, optional MessageSource sidecar dict).
        self._steering: list[tuple[str, Optional[dict[str, Any]]]] = []
        # tool_call.id → the standing rule that auto-allowed it ("tool → target"), so the
        # TOOL_FINISHED event can carry the note to the tool card (§25).
        self._standing_notes: dict[str, str] = {}
        self._interrupt_hooks: list[Callable[[], None]] = list(interrupt_hooks or [])
        # Guards the hook list: `request_interrupt` takes its snapshot under it and calls
        # the hooks outside it, so a hook that attaches or detaches another one (or simply
        # takes its time) can never corrupt the walk or deadlock against it.
        self._hooks_lock = threading.Lock()

    # -- external controls ------------------------------------------------------
    def request_interrupt(self) -> None:
        """Stop the turn as soon as possible, from ANY state: mid-stream (the producer
        thread drops the stream between chunks), mid-tool (interrupt hooks kill the
        running command), awaiting an approval/question/plan (the await resolves as
        interrupted), or between iterations (the loop checkpoint). Every pending
        tool_call still gets a tool-error result so the history never carries orphans
        (hosted templates reject them, and durable-resume would re-prompt them)."""
        self._cancel.set()
        with self._hooks_lock:
            hooks = list(self._interrupt_hooks)
        for hook in hooks:
            try:
                hook()
            except Exception:
                pass  # best-effort: a dead executor must not block the stop

    def add_interrupt_hook(self, hook: Callable[[], None]) -> Callable[[], None]:
        """Attach `hook` for as long as the returned "remove" callable is left uncalled.

        For whatever is stoppable only WHILE one call runs, as opposed to the things the
        session owns for its whole life (those go in the constructor's `interrupt_hooks`):
        `explore` relays Stop into the subagent engine it just built, and only for the
        length of that one call (tools/subagent.py).

        If Stop is already pending, `hook` is called here, before this returns — that is
        what closes the window between "the work started" and "its hook got attached".
        A hook can therefore be called twice, once from here and once from
        `request_interrupt`, so it must be idempotent and safe to call from any thread
        (`request_interrupt` itself is both). Exceptions are swallowed, as they are there.

        Attach it from INSIDE the turn: `run`/`retry`/`resume` clear the stop flag as their
        first act, so the flag this reads only means anything once the turn is under way.

        The returned callable is idempotent and detaches exactly this registration.
        """
        with self._hooks_lock:
            self._interrupt_hooks.append(hook)
        removed = False

        def remove() -> None:
            nonlocal removed
            with self._hooks_lock:
                if removed:
                    return
                removed = True
                for index, registered in enumerate(self._interrupt_hooks):
                    if registered is hook:
                        del self._interrupt_hooks[index]
                        break

        # Read AFTER the append, which is what makes "called at least once" hold whichever
        # side wins the race: appended before `request_interrupt` took its snapshot ⇒ it
        # calls the hook; appended after ⇒ the flag it had already set is visible here.
        if self._cancel.is_set():
            try:
                hook()
            except Exception:
                pass
        return remove

    async def _interruptible(self, coro: Any, interrupted: Any) -> Any:
        """Await `coro`, but resolve early with `interrupted` if the user stops the
        turn. The pending task is cancelled so an answered-later Inbox card no-ops."""
        task = asyncio.ensure_future(coro)
        cancel_wait = asyncio.ensure_future(self._cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            # The Stop wait FAILING is not the user pressing Stop. Read as one, it answers
            # a pending approval with "interrupted" and nothing says otherwise — the same
            # silence `_astream` used to hand the turn (2026-09-18).
            if cancel_wait in done and not cancel_wait.cancelled():
                failure = cancel_wait.exception()
                if failure is not None:
                    task.cancel()
                    raise failure
            if task in done:
                return task.result()
            task.cancel()
            return interrupted
        finally:
            cancel_wait.cancel()

    def queue_steering(
        self, text: str, source: Optional[dict[str, Any]] = None
    ) -> None:
        self._steering.append((text, source))

    # -- main loop --------------------------------------------------------------
    async def run(
        self,
        user_input: "str | list",
        *,
        source: Optional[dict[str, Any]] = None,
        display: Optional[str] = None,
    ) -> AsyncIterator[Event]:
        # `user_input` is a string, or OpenAI content-parts (text + image_url) for attachments.
        # `source` (a MessageSource dict) is a display-only sidecar for connector messages: it
        # rides on the persisted user message + the TURN_START event, but is stripped before the
        # message reaches a provider (see `_outbound_messages`). `content` stays the framed text.
        # `display` is the same split for force-run skills (SKILLS-SPEC §4.1 #3): the user's
        # literal "/skill …" line for the transcript, while `content` carries the model-facing
        # framing. `ts` (unix seconds, stamped on every appended message) is the same kind of
        # sidecar.
        message: dict[str, Any] = {
            "role": "user",
            "content": user_input,
            "ts": time.time(),
        }
        if source is not None:
            message["source"] = source
        if display is not None:
            message["_display"] = display
        self.messages.append(message)
        self._cancel.clear()
        if self.session_facts is not None:
            self.session_facts.begin_turn()
        # §8.4 retry guard resets per user turn: two reviewer denials in one turn route
        # everything else that turn to the human. A fresh user message is a fresh brief.
        self._reviewer_denials = 0
        self._reviewer_verdicts.clear()
        data: dict[str, Any] = {"input": user_input}
        if source is not None:
            data["source"] = source
        if display is not None:
            data["display"] = display
        yield Event(EventType.TURN_START, data)
        async for event in self._loop():
            yield event

    def switch_model(self, model: str) -> Optional[str]:
        """Rebind the session's model mid-conversation (roadmap item 3). History is
        canonical OpenAI shape and every provider converts per call, so the switch is just
        the field write — plus a persisted notice marking WHERE it happened, with a
        degradation warning when history carries images the new model can't see (those are
        sent as placeholders — see `_outbound_messages`). Returns the notice text, or None
        when nothing changed (same model, or first bind on a fresh session)."""
        if not model or model == self.model:
            return None
        # Notices (mode banner, MCP failures) are bookkeeping, not history: a model picked on
        # a draft is still its first bind — no marker, nothing to persist (owner ask 2026-09-02).
        had_history = any(m.get("role") not in ("system", "notice") for m in self.messages)
        self.model = model
        # The reviewer judges with the session's own model (§1.5: "if it's trusted to
        # drive the agent, it's strong enough to review it"). Bound once at session build,
        # it would otherwise keep the OLD model for the rest of the session after a
        # switch — silently reviewing with a model the user moved away from.
        if self.reviewer is not None:
            self.reviewer.model = model
        if not had_history:
            return None
        from .providers.matrix import model_labels

        text = f"Model switched to {model_labels().get(model, model)}"
        try:
            caps = self.provider.capabilities(model)
        except Exception:
            caps = None
        if (
            caps is not None
            and not getattr(caps, "vision", False)
            and self._history_has_images()
        ):
            text += " — earlier images can't be read by this model"
        self._append_notice("model_switch", text)
        return text

    def _history_has_images(self) -> bool:
        return any(
            isinstance(p, dict) and p.get("type") == "image_url"
            for msg in self.messages
            if isinstance(msg.get("content"), list)
            for p in msg["content"]
        )

    def _tail_is_retriable_error(self) -> bool:
        """True when the history tail is an error notice, looking through the bookkeeping
        notices appended after it (`_RETRY_TRANSPARENT_NOTICE_KINDS`: a model switch, a
        superseded Inbox answer — neither must consume the retry). `turn_aborted` counts:
        a turn the provider cut short answered nothing and did nothing, so it is exactly
        as re-runnable as a provider failure."""
        for message in reversed(self.messages):
            if message.get("role") != "notice":
                return False
            if message.get("kind") in _RETRY_TRANSPARENT_NOTICE_KINDS:
                continue
            return message.get("kind") in _RETRIABLE_NOTICE_KINDS
        return False

    def _append_notice(self, kind: str, text: Optional[str] = None, **fields: Any) -> None:
        """Persist a turn-ending marker (error/interrupted) as a display-only `notice`
        message: it survives reload like the transcript does, but `_outbound_messages`
        drops the role so no provider ever sees it. Extra `fields` (e.g. the failing
        MCP server's name) persist on the message for structured rendering."""
        notice: dict[str, Any] = {"role": "notice", "kind": kind, "ts": time.time()}
        if text:
            notice["text"] = text
        notice.update({k: v for k, v in fields.items() if v is not None})
        self.messages.append(notice)

    async def _sleep_unless_stopped(self, delay: float) -> bool:
        """Wait out one retry backoff; False when the user pressed Stop during it. The
        wait IS the cancel event's wait, so a Stop lands immediately instead of six
        seconds later — the default `retry_sleep`, replaced wholesale in tests."""
        if delay <= 0:
            return not self._cancel.is_set()
        try:
            await asyncio.wait_for(self._cancel.wait(), timeout=delay)
        except (asyncio.TimeoutError, TimeoutError):
            return not self._cancel.is_set()
        return False

    def _trusts_truncation(self) -> bool:
        """Whether `turn.truncated` means anything for the model in play — see
        `_abort_reason`. True once this model has been watched reporting a finish reason.
        """
        return self.model in self._finish_reason_seen

    def _retry_budget(
        self, reason: str, elapsed: float, *, long_attempt: bool = False
    ) -> int:
        """How many automatic retries THIS failure is worth, before the turn-wide cap.

        Three ceilings stack: the configured budget, the reason's own (a bare empty answer
        is weak evidence of a transport fault), and the cost of the attempt that just
        died — repeating a four-minute call twice more spends twelve minutes and three
        times the tokens to reach the same sentence.

        `long_attempt` forces that third ceiling on regardless of the clock. A first-chunk
        timeout passes it because the two knobs are independent: the deadline defaults to
        120s and so lands past `_LONG_ATTEMPT_DEFAULT` (90s) on its own, but
        `_LONG_ATTEMPT_ENV` can be raised above it, and then the worst case would be the
        full budget times a full deadline each — three two-minute waits before the user
        hears anything. The caller knows which failure this is, so it says so instead of
        leaving the bound to a coincidence between two defaults.
        """
        if reason not in _RETRIABLE_ABORT_REASONS and reason != "transient":
            return 0
        budget = self.model_retries
        budget = min(budget, _REASON_RETRY_CAP.get(reason, budget))
        if long_attempt or elapsed >= _long_attempt_seconds():
            budget = min(budget, _LONG_ATTEMPT_RETRIES)
        return budget

    def _may_retry(
        self,
        reason: str,
        attempt: int,
        used: int,
        elapsed: float,
        *,
        long_attempt: bool = False,
    ) -> bool:
        """Whether one more automatic attempt is allowed: this failure's budget, the
        turn-wide cap, and nobody having pressed Stop."""
        return (
            attempt < self._retry_budget(reason, elapsed, long_attempt=long_attempt)
            and used < _TURN_RETRY_CAP
            and not self._cancel.is_set()
        )

    def _announce_retry(
        self, reason: str, attempt: int, shown_max: int, elapsed: float
    ) -> Event:
        """Persist the marker for one automatic retry and return the live event. The text
        is server-authored English; `reason`/`attempt`/`max` travel structured beside it so
        the GUI renders its own localized sentence (modeNotice.ts). `shown_max` is what is
        actually still available — the per-call budget capped by what's left of the turn's
        — so the counter never promises a retry that can't happen."""
        text = _TURN_RETRY_TEXT.get(reason, _TURN_RETRY_TEXT["transient"]).format(
            attempt=attempt, max=shown_max
        )
        self._append_notice(
            "turn_retry", text, reason=reason, attempt=attempt, max=shown_max
        )
        # The only log line a retried attempt gets (the abort line is for the one that
        # finally gives up). A retry that recovers leaves nothing in the transcript worth
        # reading later, so this is where "that relay drops one call in five" becomes
        # countable.
        logger.info(
            "turn_retry: session=%s reason=%s attempt=%d/%d model=%s elapsed=%.1fs",
            self.audit_context.get("session_id") or "-",
            reason,
            attempt,
            shown_max,
            self.model,
            elapsed,
        )
        return Event(
            EventType.TURN_RETRY,
            {"text": text, "reason": reason, "attempt": attempt, "max": shown_max},
        )

    def _log_abnormal_turn(
        self,
        kind: str,
        reason: str,
        turn: AssistantTurn,
        iterations: int,
        elapsed: float,
    ) -> None:
        """One line per turn that didn't end cleanly, and only for the attempt that was
        NOT retried — a retried one is already on the log as `turn_retry`. There was no
        log at all for any of this before: a severed stream left the server log completely
        silent, so the only evidence of the failure was the user noticing nothing had
        happened. Everything needed to tell the shapes apart is on the line, including
        whether usage arrived (a stream that stops before the usage frame is the classic
        severed one)."""
        logger.info(
            "%s: session=%s round=%d reason=%s finish_reason=%s usage=%s "
            "reasoning_chars=%d text_chars=%d tool_calls=%d elapsed=%.1fs",
            kind,
            self.audit_context.get("session_id") or "-",
            iterations,
            reason,
            turn.finish_reason or "-",
            "yes" if turn.usage is not None else "no",
            len(turn.reasoning or ""),
            len(turn.text or ""),
            len(turn.tool_calls),
            elapsed,
        )

    async def retry(self) -> AsyncIterator[Event]:
        """Re-run the model loop after a provider error — no new user message; the failed
        turn's input is already the tail of history. Guarded on the tail being an error
        notice so a stray retry frame can't re-answer a completed turn. Trailing
        model_switch notices don't break the guard — switching models and THEN retrying
        is the intended recovery path (owner-hit 2026-07-23) — and neither do
        answer_superseded ones (`_RETRY_TRANSPARENT_NOTICE_KINDS`).

        Nothing is cut from history: the notices stay where they are, the re-run's output
        is appended after them, and `_outbound_messages` drops every notice before a
        provider sees the thread. So an answer_superseded notice between the error and the
        re-run stays in the transcript, still saying what it said."""
        if not self._tail_is_retriable_error():
            return
        self._cancel.clear()
        yield Event(EventType.TURN_START, {"input": ""})
        async for event in self._loop():
            yield event

    async def resume(self) -> AsyncIterator[Event]:
        """Continue a turn that was suspended at a prompt and persisted — durable resume after a
        restart (or engine eviction). Re-process the trailing assistant message's UNANSWERED
        tool-calls (the prompt callbacks find the already-resolved Inbox item and return without
        re-prompting; answered calls are skipped, so nothing double-executes), then run the model
        loop to finish the turn."""
        pending = self._unanswered_trailing_tool_calls()
        if not pending:
            return
        self._cancel.clear()
        yield Event(EventType.TURN_START, {"input": "(resumed)"})
        async for event in self._handle_tool_calls(pending):
            yield event
        yield Event(EventType.ITERATION_END, {"iteration": 0})
        # Deliberately NOT gated on the stop flag any more. Returning here left a turn the
        # user had stopped ending on `ITERATION_END` and nothing else — no `INTERRUPTED`
        # event, no `interrupted` notice — so the transcript read as a resume that simply
        # finished, which is the same silence the severed-stream work went after (a turn
        # must never end without saying how). `_loop`'s first act is that same stop
        # checkpoint, which ends the turn exactly the way every other stop path does, and
        # it costs nothing: the check runs before the round does, so a stopped resume still
        # makes no model call. Every pending call already has its result by here
        # (`_handle_tool_calls` answers the ones it skips), so nothing is orphaned either.
        async for event in self._loop():
            yield event

    def _unanswered_trailing_tool_calls(self) -> list[ToolCall]:
        """The tool-calls of the last assistant message that don't yet have a tool result —
        i.e. the prompt we suspended on (+ any after it). Reconstructed from the persisted thread.
        """
        answered = {
            m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"
        }
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return []
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                out: list[ToolCall] = []
                for tc in msg["tool_calls"]:
                    if tc.get("id") in answered:
                        continue
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    out.append(
                        ToolCall(id=tc.get("id"), name=fn.get("name"), arguments=args)
                    )
                return out
        return []

    async def _loop(self) -> AsyncIterator[Event]:
        iterations = 0
        spent = 0  # billed tokens this turn: prompt-side + output, accumulated per round
        # Automatic retries: `attempt` counts them for the round-trip being made right
        # now (reset the moment a round delivers something), `retries_used` for the whole
        # turn. A retry re-enters this loop WITHOUT spending an iteration — see the
        # `iterations -= 1` before each `continue`, which the increment below undoes.
        attempt = 0
        retries_used = 0
        while True:
            # Stop, asked BEFORE the round is paid for. The checkpoint at the bottom of
            # this body catches a Stop that landed during tool calls, but nothing caught
            # one that landed before a round's first model call: `run`/`retry` clear the
            # flag as their very first act, so a Stop that arrives just after that used to
            # buy a whole round-trip whose answer is thrown away two screens further down
            # (`self._cancel.is_set() and turn is None`). That window is not theoretical:
            # it is how `explore` relays the parent session's Stop into its child engine
            # (tools/subagent.py). The hook is attached on the child's first event, and
            # `add_interrupt_hook` fires it on the spot when a Stop is already pending, so
            # the child's flag is routinely set between `run()` clearing it and this loop
            # starting. Skipping the call also means no producer thread is started, so no
            # provider connection is opened only to be left hanging for a dead turn.
            if self._cancel.is_set():
                self._append_notice("interrupted")
                yield Event(EventType.INTERRUPTED, {"iterations": iterations})
                return
            # Two gates, whichever trips first. Both payloads carry BOTH numbers: a stop
            # that says only "max iterations reached" tells the user about a mechanism
            # instead of about their bill, and doesn't mention that replying continues —
            # so the session sits idle, the provider cache goes cold, and resuming costs
            # more than finishing would have.
            if iterations >= self.max_iterations:
                yield Event(
                    EventType.TURN_END,
                    {
                        "status": "max_iterations_exceeded",
                        "iterations": iterations,
                        "tokens": spent,
                    },
                )
                return
            if self.max_turn_tokens and spent >= self.max_turn_tokens:
                yield Event(
                    EventType.TURN_END,
                    {
                        "status": "max_tokens_exceeded",
                        "iterations": iterations,
                        "tokens": spent,
                    },
                )
                return
            iterations += 1

            # Auto-compaction checkpoint (OPE-27): between tool turns and before a new
            # turn's first call. Deliberately no "wrap up" warning to the model. The
            # COMPACTING signal precedes the (multi-second) summarizer call so surfaces
            # can show progress instead of a silent stall.
            notice = None
            if self._compaction_due():
                yield Event(EventType.COMPACTING, {})
                notice = await self._compact_now()
            if notice:
                self._append_notice("compacted", notice)
                yield Event(EventType.COMPACTED, {"text": notice})

            turn: Optional[AssistantTurn] = None
            streamed: list[str] = []
            streamed_reasoning: list[str] = []
            # Wall-clock for this round-trip. Reported in the abnormal-ending log line —
            # a stream severed after four minutes reads very differently from one that
            # came back empty in two seconds — and it also decides how much of the retry
            # budget the failure is worth (`_retry_budget`).
            round_started = self.clock()

            def _partial_turn() -> AssistantTurn:
                # What the user watched arrive — text and thinking, NO tool calls (any
                # half-formed calls would either orphan or execute against the stop).
                return AssistantTurn(
                    text="".join(streamed) or None,
                    reasoning="".join(streamed_reasoning) or None,
                )

            try:
                async for chunk in self._astream():
                    if chunk.reasoning_delta:
                        streamed_reasoning.append(chunk.reasoning_delta)
                        yield Event(
                            EventType.REASONING_DELTA, {"text": chunk.reasoning_delta}
                        )
                    if chunk.text_delta:
                        streamed.append(chunk.text_delta)
                        yield Event(
                            EventType.ASSISTANT_DELTA, {"text": chunk.text_delta}
                        )
                    if chunk.turn is not None:
                        turn = chunk.turn
            except Exception as exc:  # provider failure
                # A raw context-overflow 400 (compaction mispredicted, e.g. the estimate
                # path) routes into the compaction policy instead of surfacing. The retry
                # is progress-guarded: each pass moves the boundary forward or gives up,
                # so a model that keeps overflowing still terminates in the error path.
                if _compaction.is_context_overflow(exc) and not self._cancel.is_set():
                    yield Event(EventType.COMPACTING, {})
                    notice = await self._compact_now(force=True)
                    if notice:
                        self._append_notice("compacted", notice)
                        yield Event(EventType.COMPACTED, {"text": notice})
                        continue
                # A call that never landed — connection reset, timeout, 429, 5xx — is a
                # failure of the wire, not an answer from the model, so re-send it instead
                # of handing the user a Retry button for work a machine can do. Only while
                # NO text has streamed: the user has already read whatever arrived, and a
                # second attempt would print it twice (the same rule aigateway_provider
                # applies to its own mid-stream re-send). Thinking text doesn't count —
                # the surfaces drop it when the retry is announced.
                elapsed = self.clock() - round_started
                # A first-chunk timeout is a long attempt BY CONSTRUCTION, whatever the
                # clock says — see `_retry_budget`. (`elapsed` here is the whole round,
                # which for this failure is the deadline plus whatever preceded the call;
                # the flag is what keeps the bound from depending on that.)
                long_attempt = isinstance(exc, FirstChunkTimeout)
                if (
                    not streamed
                    and is_transient_model_error(exc)
                    and self._may_retry(
                        "transient",
                        attempt,
                        retries_used,
                        elapsed,
                        long_attempt=long_attempt,
                    )
                ):
                    shown_max = min(
                        self._retry_budget(
                            "transient", elapsed, long_attempt=long_attempt
                        ),
                        _TURN_RETRY_CAP - retries_used,
                    )
                    attempt += 1
                    retries_used += 1
                    yield self._announce_retry("transient", attempt, shown_max, elapsed)
                    if not await self.retry_sleep(
                        _retry_delay(attempt, retry_after_seconds(exc))
                    ):
                        self._append_notice("interrupted")
                        yield Event(EventType.INTERRUPTED, {"iterations": iterations})
                        return
                    # Anything the user typed while this call was dying (or during the
                    # backoff) belongs in the prompt the retry sends — they are watching
                    # "retrying…" and correcting course, not queueing for later.
                    if self._steering:
                        self._inject_steering()
                    iterations -= 1  # a retry re-runs the round; it doesn't spend one
                    continue
                # Same contract as the stop path below: the partial the user watched
                # arrive survives the failure.
                if streamed or streamed_reasoning:
                    self.messages.append(_assistant_message(_partial_turn()))
                friendly = friendly_model_error(self.model, exc)
                payload = {
                    "error": friendly or str(exc),
                    "error_type": type(exc).__name__,
                }
                if friendly:
                    payload["raw"] = str(exc)
                self._append_notice("error", friendly or str(exc))
                yield Event(EventType.ERROR, payload)
                return
            if self._cancel.is_set() and turn is None:
                # Stopped mid-stream: persist exactly what the user watched arrive.
                if streamed or streamed_reasoning:
                    self.messages.append(_assistant_message(_partial_turn()))
                self._append_notice("interrupted")
                yield Event(EventType.INTERRUPTED, {"iterations": iterations})
                return
            if turn is None:
                turn = AssistantTurn()
            if turn.usage is not None:
                # The trigger signal: the prompt-side total that actually occupied the
                # window on this round-trip (estimate fallback when never reported).
                self._last_context_tokens = turn.usage.context_tokens
                # …and the running bill for the token gate. Prompt-side is re-sent whole
                # every round, so this sums what was actually billed, not the context
                # size. No price table exists in the repo, so the unit is tokens: a
                # cached read and a fresh one count the same here even though they cost
                # 10x apart — the gate is a runaway backstop, not an accountant.
                spent += turn.usage.context_tokens + turn.usage.output

            self._turn_truncated = turn.finish_reason == "length"
            _sanitize_mangled_calls(turn)
            if turn.finish_reason is not None:
                # This model DOES report finish reasons, so from here on its silence means
                # something — see `_abort_reason`. Keyed by model id, so switching to one
                # we've never watched starts the observation over.
                self._finish_reason_seen.add(self.model)
            elapsed = self.clock() - round_started

            # Nothing at all came back — no answer, no tool call. Ending as "completed"
            # here is the same lie the unparsed-call branch below refuses to tell: the GUI
            # shows the thinking text trailing off and the turn just stops, so the user
            # reads a cut-off stream as work that got done (owner report 2026-09-18 — 3.3k
            # of thinking ending on "Write file to …", no file, no error, nothing in the
            # log). Handled BEFORE anything is persisted, so a RETRIED attempt re-sends
            # the history the dead attempt was given — byte-identical unless steering
            # arrived meanwhile, which is deliberately injected into the re-send.
            if not turn.tool_calls and not (turn.text or "").strip():
                reason = _abort_reason(turn, trust_truncated=self._trusts_truncation())
                if self._may_retry(reason, attempt, retries_used, elapsed):
                    shown_max = min(
                        self._retry_budget(reason, elapsed),
                        _TURN_RETRY_CAP - retries_used,
                    )
                    attempt += 1
                    retries_used += 1
                    yield self._announce_retry(reason, attempt, shown_max, elapsed)
                    if not await self.retry_sleep(_retry_delay(attempt)):
                        self._append_notice("interrupted")
                        yield Event(EventType.INTERRUPTED, {"iterations": iterations})
                        return
                    # Anything the user typed while this call was dying (or during the
                    # backoff) belongs in the prompt the retry sends — they are watching
                    # "retrying…" and correcting course, not queueing for later.
                    if self._steering:
                        self._inject_steering()
                    iterations -= 1  # a retry re-runs the round; it doesn't spend one
                    continue
                self._log_abnormal_turn(
                    "turn_aborted", reason, turn, iterations, elapsed
                )
                if turn.reasoning:
                    # Giving up for good: the thinking the user watched for four minutes
                    # is the only thing this turn produced, so it stays on screen and in
                    # the record. `aborted` makes `_outbound_messages` drop the WHOLE
                    # message — an empty assistant turn re-sent on every later call is
                    # exactly what the retry path above refuses to create.
                    self.messages.append(
                        _assistant_message(turn, model=self.model, aborted=True)
                    )
                # Steering queued while the dead turn ran must not be swallowed: nothing
                # else will ever answer it (it isn't in history and never reached the
                # dead-letter box), and held back it silently resurfaces in the MIDDLE of
                # the next turn, after that turn's first answer. It goes in BEFORE the
                # notice so the notice stays the tail: that is what keeps Retry on offer
                # (`_tail_is_retriable_error`), and the re-run then carries the steering
                # the user just sent — which is exactly what they were asking for.
                if self._steering:
                    self._inject_steering()
                message = _TURN_ABORTED_TEXT[reason]
                if attempt:
                    message += _TURN_ABORTED_RETRIED.format(n=attempt)
                self._append_notice(
                    "turn_aborted", message, reason=reason, retries=attempt or None
                )
                yield Event(
                    EventType.ERROR,
                    {
                        "error": message,
                        "error_type": "TurnAborted",
                        "reason": reason,
                        **({"retries": attempt} if attempt else {}),
                    },
                )
                return
            attempt = 0  # this round delivered something; the next one starts fresh

            self.messages.append(_assistant_message(turn, model=self.model))
            payload: dict[str, Any] = {
                "text": turn.text,
                "tool_calls": [tc.name for tc in turn.tool_calls],
            }
            if turn.reasoning:
                payload["reasoning"] = turn.reasoning
            if turn.usage is not None:
                payload["usage"] = {"model": self.model, **turn.usage.as_dict()}
            yield Event(EventType.ASSISTANT_MESSAGE, payload)

            # Something DID arrive, but it was cut off. It stays (the user has already
            # read it) and the turn carries on — this is a warning appended after the
            # message, not a failure. Deliberately outside the no-tool-calls branch: a
            # turn that hit the ceiling mid-tool-call is exactly how the mangled-arguments
            # path gets fed, and the user deserves to know why the tool got half a call.
            # Membership in _TURN_TRUNCATED_TEXT IS the "was it cut?" test — `_abort_reason`
            # answers "length"/"no_finish" only on a real cut signal and plain "empty"
            # (absent from that table) for every ordinary ending.
            cut_reason = _abort_reason(turn, trust_truncated=self._trusts_truncation())
            if cut_reason in _TURN_TRUNCATED_TEXT:
                message = _TURN_TRUNCATED_TEXT[cut_reason]
                self._log_abnormal_turn(
                    "turn_truncated", cut_reason, turn, iterations, elapsed
                )
                self._append_notice("turn_truncated", message, reason=cut_reason)
                yield Event(
                    EventType.TURN_TRUNCATED, {"text": message, "reason": cut_reason}
                )

            if not turn.tool_calls:
                if self._steering:
                    self._inject_steering()
                    continue
                # The model tried to call a tool and the syntax never parsed — salvage already
                # had its go. Ending as "completed" here would present a half-written call as
                # the answer, which is indistinguishable from the model deciding it was done;
                # the user just sees narration trailing off into stray tags. Fail loudly
                # instead, on the error path so the GUI offers Retry — this is drift, not a
                # deterministic failure, so retrying the same model usually works.
                if looks_like_unparsed_tool_call(turn.text, self.registry.schemas() or None):
                    message = (
                        f"{self.model} replied with a tool call this endpoint couldn't parse, "
                        "so the turn was stopped rather than answered from a partial call. "
                        "Retry, or switch to a larger model — smaller local models drift off "
                        "the tool-call format, especially with many tools in play."
                    )
                    self._append_notice("error", message)
                    yield Event(
                        EventType.ERROR,
                        {"error": message, "error_type": "UnparsedToolCall"},
                    )
                    return
                yield Event(
                    EventType.TURN_END,
                    {"status": "completed", "iterations": iterations},
                )
                return

            async for event in self._handle_tool_calls(turn.tool_calls):
                yield event

            yield Event(EventType.ITERATION_END, {"iteration": iterations})

            if self._cancel.is_set():
                self._append_notice("interrupted")
                yield Event(EventType.INTERRUPTED, {"iterations": iterations})
                return
            if self._steering:
                self._inject_steering()

    # -- auto-compaction (OPE-27) ------------------------------------------------
    def _compaction_config(self) -> dict[str, Any]:
        cfg = dict(self.compaction_settings() or {}) if self.compaction_settings else {}
        if not cfg.get("context_window"):
            from .providers.matrix import model_context_windows

            cfg["context_window"] = model_context_windows().get(self.model)
        cfg.setdefault("threshold_pct", _compaction.DEFAULT_THRESHOLD_PCT)
        cfg.setdefault("cap_tokens", _compaction.DEFAULT_CAP_TOKENS)
        return cfg

    def _compaction_due(self) -> bool:
        """The trigger check alone — cheap and side-effect free, so the loop can emit
        the COMPACTING signal before committing to the (slow) summarizer call."""
        cfg = self._compaction_config()
        if cfg.get("enabled") is False:
            return False
        signal = self._last_context_tokens or _compaction.estimate_tokens(
            self._outbound_messages()
        )
        return _compaction.should_compact(
            signal,
            cfg.get("context_window"),
            threshold_pct=float(cfg["threshold_pct"]),
            cap_tokens=int(cfg["cap_tokens"]),
        )

    async def _compact_now(self, *, force: bool = False) -> Optional[str]:
        """Run the compaction policy. Callers gate on `_compaction_due()` (or `force`,
        the overflow path). Returns the user-facing notice text when the outbound view
        changed, else None. Failure policy per spec: retry once (both modes); attended →
        Retry / Trim prompt; unattended → auto-trim and continue (never park a run on
        bookkeeping)."""
        cfg = self._compaction_config()
        pct = float(cfg["threshold_pct"])
        cap = int(cfg["cap_tokens"])
        window = cfg.get("context_window")
        keep = int(
            _compaction.KEEP_RECENT_FRACTION
            * _compaction.trigger_tokens(window, threshold_pct=pct, cap_tokens=cap)
        )
        model = str(cfg.get("model") or "") or self.model

        def _build() -> Optional[_compaction.CompactionState]:
            return _compaction.build_state(
                self.messages,
                provider=self.provider,
                model=model,
                keep_tokens=keep,
                prior=self.compaction_state,
            )

        state: Optional[_compaction.CompactionState] = None
        failed = False
        for _attempt in range(2):  # first try + the unconditional single retry
            try:
                state = await asyncio.to_thread(_build)
                failed = False
                break
            except Exception:
                failed = True
        if failed and self.question_asker is not None and self.is_attended and self.is_attended():
            while True:
                answer = await self._interruptible(
                    self.question_asker(
                        {
                            "question": (
                                "Context compaction failed — the summarizer couldn't "
                                "condense this session's history. How should I proceed?"
                            ),
                            "options": ["Retry", "Trim oldest 10%"],
                            "allow_text": False,
                            "header": "Compaction",
                        },
                        None,
                    ),
                    interrupted=None,
                )
                if not answer or answer.get("answer") != "Retry":
                    break
                try:
                    state = await asyncio.to_thread(_build)
                    failed = False
                    break
                except Exception:
                    continue
        if state is not None:
            self.compaction_state = state
            self._last_context_tokens = None  # stale once the outbound view shrank
            return "Context compacted — earlier turns were summarized"
        if failed or force:
            trimmed = _compaction.trim_state(self.messages, prior=self.compaction_state)
            if trimmed is not None:
                self.compaction_state = trimmed
                self._last_context_tokens = None
                return "Context trimmed — oldest turns dropped (summary unavailable)"
        return None

    # -- helpers ----------------------------------------------------------------
    async def _astream(self):
        """Bridge the provider's blocking stream generator to the async loop via a
        thread + queue, so text deltas surface live without blocking the event loop.

        Raises `FirstChunkTimeout` when the provider accepts the request and then sends
        nothing at all for `self.first_chunk_timeout` seconds — bounding the wait only,
        not the socket, and only before the first chunk. Raises `StreamBridgeError` on the
        one outcome documented there, and returns quietly on the ordinary Stop.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        tools = self.registry.schemas() or None
        model, messages, settings = (
            self.model,
            self._outbound_messages(),
            self.model_settings,
        )
        provider = self.provider
        # Set when THIS stream's consumer leaves, for any reason at all: normal end, Stop,
        # `aclose`/GeneratorExit, cancellation, error. One per stream (never engine state),
        # so an abandoned producer stops pulling the wire instead of draining a whole
        # response into a queue that was thrown away with the generator.
        consumer_gone = threading.Event()
        # When the producer thread actually began pulling the wire, or None while it is
        # still waiting for a slot in the executor. Written once from that thread and read
        # from the loop — a single float assignment, which is why no lock is needed. This
        # is what the first-chunk deadline is measured from; see the branch that reads it.
        started_at: list[Optional[float]] = [None]

        def deliver(item) -> bool:
            """Hand `item` to the consumer's loop; False once that loop has been closed.

            A Stop ends the consumer at once, while this thread can still be inside a
            provider read that nothing interrupts. `explore` closes its child loop without
            waiting for it (tools/subagent.py), so when the read finally returns there may
            be no loop left, and `call_soon_threadsafe` raises on a closed one. Nobody is
            listening by then, so the item is dropped rather than raised: raised, it would
            only land in the executor's future, which nobody reads — and on the error path
            it would replace the provider's own exception.
            """
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # the loop is closed; nobody is left to read this
                return False
            return True

        def produce():
            # "The wire is being pulled from NOW", and the only thing that starts the
            # first-chunk clock. The producer runs on the DEFAULT executor, shared with
            # `_handle_tool_calls`' `to_thread` and dozens of `to_thread` calls in
            # `server/`, so under concurrency this thread can sit in the pool's queue for
            # an unbounded time before it runs at all. Timing that wait as if the provider
            # were slow would invent a timeout and retry into the very queue that caused
            # it — so until this is written, there is no deadline.
            #
            # Written before the call, and claiming no more than that. Providers differ on
            # when they touch the wire: `stream()` is a generator function on OpenAI,
            # Anthropic, Gemini, the AI Gateway and the Responses API (so nothing at all
            # happens until the first `next()` a line below) and a plain function
            # returning an iterator on Bedrock, Vertex and the router. What is true for
            # every one of them at this line is that this thread is RUNNING rather than
            # queued, which is the distinction the deadline needs.
            started_at[0] = self.clock()
            try:
                for chunk in provider.stream(
                    model=model, messages=messages, tools=tools, **settings
                ):
                    # User pressed Stop, or nobody is reading any more: drop the stream
                    # between chunks (reading either flag from a thread is safe — both are
                    # plain attribute reads, and we only read).
                    if self._cancel.is_set() or consumer_gone.is_set():
                        break
                    if not deliver(("chunk", chunk)):
                        break  # nobody left to read: let go of the stream, like a Stop
            except Exception as exc:  # surfaced to the awaiting consumer
                deliver(("error", exc))
            finally:
                deliver(("done", None))

        loop.run_in_executor(None, produce)
        get_task: Optional[asyncio.Future] = None
        cancel_task: Optional[asyncio.Future] = None
        # `deadline` is the configured first-chunk bound (None switches it off), read once
        # so a mid-stream attribute change can't confuse the arithmetic below. `armed` is
        # what THIS wait is given: the deadline until a chunk arrives, then None forever.
        deadline = self.first_chunk_timeout
        armed: Optional[float] = deadline
        try:
            while True:
                # Race the queue against Stop so a stalled stream (no chunks arriving —
                # the pre-first-token wait, a wedged connection) can't hold the turn, and
                # against the first-chunk deadline while that is still armed.
                if get_task is None:
                    get_task = asyncio.ensure_future(queue.get())
                cancel_task = asyncio.ensure_future(self._cancel.wait())
                done, _ = await asyncio.wait(
                    {get_task, cancel_task},
                    timeout=armed,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Five outcomes now (the deadline joined the four), told apart on purpose.
                # Collapsing them into "not the queue, so the user stopped" is what
                # silently dropped the last frame of a stream — reliably the
                # `StreamChunk(turn=…)`, since that one always arrives after a wait — and
                # handed the turn an empty answer instead.
                stop_failed = (
                    cancel_task.exception()
                    if cancel_task in done and not cancel_task.cancelled()
                    else None
                )
                cancel_task.cancel()
                if stop_failed is not None:
                    get_task.cancel()
                    raise stop_failed
                if get_task in done:
                    kind, payload = get_task.result()
                    get_task = None
                    if kind == "chunk":
                        if armed is not None:
                            began = started_at[0]
                            waited = self.clock() - began if began is not None else 0.0
                            # Against the configured deadline, never against `armed` —
                            # `armed` may be the remainder of a re-armed wait.
                            if waited > (deadline or 0.0) * _SLOW_FIRST_CHUNK_FRACTION:
                                # Telemetry only, and the reason it is here rather than in
                                # the timeout branch: what a between-chunks deadline would
                                # have to be set to is knowable only from streams that DID
                                # answer, slowly. Nothing branches on it.
                                logger.info(
                                    "slow_first_chunk: session=%s model=%s "
                                    "elapsed=%.1fs",
                                    self.audit_context.get("session_id") or "-",
                                    self.model,
                                    waited,
                                )
                        # Disarmed for the rest of the stream — any chunk counts, thinking
                        # text included. Nothing bounds the gaps between chunks.
                        armed = None
                        yield payload
                        continue
                    if kind == "error":
                        raise payload
                    return
                # Neither task finished, so `asyncio.wait`'s own timeout expired — the one
                # way `done` can be empty, and the only way the first-chunk deadline can
                # fire. This HAS to be asked before the `StreamBridgeError` below: that one
                # is reached by falling through, so a deadline that fired here would
                # otherwise be reported as "a second turn was started on this engine",
                # which is a different bug with a different fix and no automatic retry.
                if not done:
                    began = started_at[0]
                    waited = self.clock() - began if began is not None else 0.0
                    if began is None or waited < deadline:
                        # Either the producer is STILL QUEUED in the shared default
                        # executor — nothing has been asked of the provider, so there is
                        # nothing to time yet — or it got its slot part-way through this
                        # wait, and what is owed is the rest of ITS clock, not another
                        # whole deadline. Either way, wait again.
                        #
                        # The queue task is dropped and remade rather than carried: a
                        # pending `Queue.get()` leaves the item in the queue, so nothing
                        # is lost, and it cannot be left registered or the next
                        # `put_nowait` would wake an orphan that nobody is awaiting. It is
                        # provably still pending here — `asyncio.wait` returned with it
                        # unfinished and no await has run since.
                        get_task.cancel()
                        get_task = None
                        armed = deadline if began is None else max(deadline - waited, 0.0)
                        if began is None:
                            # The one arm of the five that neither raises, returns nor
                            # yields, and the only one with no bound: while the shared
                            # pool stays full this re-arms forever, which is once again a
                            # spinner with an empty server log — the exact failure this
                            # whole block was added to end. One line at INFO keeps it
                            # findable, and it can repeat at most once per deadline.
                            logger.info(
                                "first_chunk_deadline_waiting_on_executor: "
                                "session=%s model=%s",
                                self.audit_context.get("session_id") or "-",
                                self.model,
                            )
                        continue
                    get_task.cancel()
                    logger.info(
                        "first_chunk_timeout: session=%s model=%s waited=%.1fs",
                        self.audit_context.get("session_id") or "-",
                        self.model,
                        waited,
                    )
                    # Whole seconds for the ordinary case (the default is 120), two
                    # decimals below one — a deadline set in milliseconds must not report
                    # itself as "sent nothing for 0s".
                    shown = f"{waited:.0f}" if waited >= 1 else f"{waited:.2f}"
                    raise FirstChunkTimeout(
                        f"{self.model} accepted the request but sent nothing for "
                        f"{shown}s — the connection looks wedged. "
                        f"({_FIRST_CHUNK_TIMEOUT_ENV})"
                    )
                get_task.cancel()
                if self._cancel.is_set():
                    return  # interrupted — the producer exits on its own next chunk
                raise StreamBridgeError(
                    "the model stream ended without delivering a turn and without a stop "
                    "signal"
                )
        finally:
            # Whatever the exit — return, raise, Stop, `aclose`, cancellation — tell the
            # producer nobody is reading and leave no waiter registered on the stop flag.
            # Nothing awaits here: a `finally` that awaits during GeneratorExit is an error.
            consumer_gone.set()
            for task in (get_task, cancel_task):
                if task is not None and not task.done():
                    task.cancel()

    async def _handle_tool_calls(
        self, tool_calls: list[ToolCall]
    ) -> AsyncIterator[Event]:
        """Run one assistant turn's tool calls: authorize all of them first (sequentially —
        approval prompts are interactive), then execute. Low-risk calls (reads, searches)
        run concurrently; everything else runs one at a time in call order."""
        # Auto-Approve: fire the reviewer for every call that will need it, all at once,
        # BEFORE the sequential authorize loop (spec §8.6 — one action per request, sent
        # concurrently; the wall-clock cost of reviewing N calls is one round-trip, and a
        # verdict physically cannot land on the wrong action). The loop below stays
        # sequential because approval cards are interactive and must reach the human one
        # at a time, in call order.
        await self._preconsult_reviewer(tool_calls)
        cleared: list[ToolCall] = []
        for tool_call in tool_calls:
            if self._cancel.is_set():
                # Stopped: every remaining call still gets an answer (no orphans).
                yield self._interrupted_tool(tool_call)
                continue
            yield Event(
                EventType.TOOL_PROPOSED,
                {"name": tool_call.name, "arguments": tool_call.arguments},
            )
            self._audit(tool_call, stage="proposed")
            if _is_mangled(tool_call):
                # The arguments never parsed as JSON (a `{"_raw": …}` fallback from the
                # provider). Executing would produce a bare parameter error the model
                # misreads — seen in the field as an endless "wrong parameter" retry
                # loop. Answer with the ACTUAL diagnosis instead.
                yield self._mangled_tool(tool_call)
                continue
            # `request_directory` and `propose_plan` are interactive: the user decides
            # out-of-band and that decision IS the consent, so they skip the
            # permission/registry path.
            if tool_call.name == "request_directory":
                async for event in self._handle_directory_request(tool_call):
                    yield event
                continue
            if tool_call.name == "request_tool":
                async for event in self._handle_tool_request(tool_call):
                    yield event
                continue
            if tool_call.name == "propose_plan":
                async for event in self._handle_plan_proposal(tool_call):
                    yield event
                continue
            if tool_call.name == "propose_team":
                async for event in self._handle_team_proposal(tool_call):
                    yield event
                continue
            if tool_call.name == "propose_work_items":
                async for event in self._handle_items_proposal(tool_call):
                    yield event
                continue
            if tool_call.name == "ask_user":
                async for event in self._handle_ask_user(tool_call):
                    yield event
                continue
            allowed = False
            async for item in self._authorize(tool_call):
                if isinstance(item, Event):
                    yield item
                else:
                    allowed = item
            if allowed:
                cleared.append(tool_call)

        concurrent = (
            [tc for tc in cleared if self._parallel_safe(tc)]
            if len(cleared) > 1
            else []
        )
        serial = [tc for tc in cleared if tc not in concurrent]

        if concurrent:
            if self._cancel.is_set():
                # Stopped before this batch was dispatched: give every call in it the
                # same stop-path answer the serial loop below gives its own calls —
                # don't gather the batch.
                for tool_call in concurrent:
                    yield self._interrupted_tool(tool_call)
            else:
                for tool_call in concurrent:
                    yield Event(EventType.TOOL_STARTED, {"name": tool_call.name})
                    self._audit(tool_call, stage="started")
                outcomes = await asyncio.gather(
                    *[self._run_tool(tc) for tc in concurrent]
                )
                for tool_call, outcome in zip(concurrent, outcomes):
                    if outcome is None:
                        yield self._abandoned_tool(tool_call)
                    else:
                        yield self._record_result(tool_call, *outcome)

        for tool_call in serial:
            if self._cancel.is_set():
                yield self._interrupted_tool(tool_call)
                continue
            yield Event(EventType.TOOL_STARTED, {"name": tool_call.name})
            self._audit(tool_call, stage="started")
            outcome = await self._run_tool(tool_call)
            if outcome is None:
                yield self._abandoned_tool(tool_call)
            else:
                yield self._record_result(tool_call, *outcome)

    # -- running one authorized call, and not waiting forever for it -------------------

    async def _run_tool(self, tool_call: ToolCall) -> Optional[tuple[Any, str]]:
        """Execute one authorized call and return its `(result, status)`, or None when
        the turn was stopped and this call's tool is one we stop WAITING for.

        Tools that are not abandonable keep exactly the old behaviour: the turn waits for
        the thread, however long it takes.
        """
        if not self._abandonable(tool_call):
            return await asyncio.to_thread(self._execute_sync, tool_call)
        return await self._run_tool_interruptibly(tool_call)

    def _abandonable(self, tool_call: ToolCall) -> bool:
        """Whether Stop may stop WAITING for this tool instead of waiting it out.

        Abandoning a wait does not stop the tool — the thread runs to completion and its
        result is thrown away — so it is only ever safe where the discarded result is the
        whole loss. That is what the classification is asked for: `RiskClass.READ` (plus
        the two read-only network tools, which classify EGRESS because the model chooses
        their destination — the gate cares about the outbound query, this does not).

        Three deliberate exclusions inside that set:

        * Tools that stop THEMSELVES and come back with a truthful result when they do:
          MCP calls, whose future is cancelled by an interrupt hook (coworker/mcp/tools.py)
          and which come back as interrupted within the same stop, and the ones named in
          `_SELF_INTERRUPTING_TOOLS`. Abandoning the wait would win that race and replace
          an accurate "interrupted by user" with "result unavailable". `all` is the manual
          override that gives that distinction up.
        * Tools that classify READ but change state which outlives the turn:
          `_SIDE_EFFECTING_READS` by name, and the on-demand loaders by category.
          `classify` returns READ as a FALLBACK for anything it does not know that
          declares no approval, so without these the invariant this path rests on —
          discarding the result is the WHOLE loss — would simply be false for them. See
          those constants for the enumeration and for how it was obtained; all of them are
          fast, so the exclusion costs Stop next to nothing.

        The set is therefore only as good as the enumeration: a NEW tool that classifies
        READ and quietly mutates something joins it automatically. Making that structural
        rather than vigilant would mean an explicit allowlist instead of a fallback
        classification, which is a larger change than this one.
        """
        mode = _abandon_mode()
        if mode == "none":
            return False
        if mode == "all":
            return True
        spec = self.registry.get(tool_call.name)
        metadata = spec.metadata if spec else None
        category = getattr(metadata, "category", "")
        if category == "mcp" or tool_call.name in _SELF_INTERRUPTING_TOOLS:
            return False
        if (
            category == _SIDE_EFFECTING_READ_CATEGORY
            or tool_call.name in _SIDE_EFFECTING_READS
        ):
            return False
        if tool_call.name in _ABANDONABLE_EGRESS_TOOLS:
            return True
        return (
            classify(tool_call.name, metadata, self.permissions.risk_overrides)
            is RiskClass.READ
        )

    async def _run_tool_interruptibly(
        self, tool_call: ToolCall
    ) -> Optional[tuple[Any, str]]:
        """`_execute_sync` in a worker thread, racing the turn's Stop flag. Returns the
        tool's `(result, status)` when the tool wins, None when Stop does.

        Deliberately NOT `_interruptible`, and deliberately not cancelling the task:
        `task.cancel()` does nothing to a thread. Measured 2026-09-22 (scratchpad probe
        `itc_probe3.py`, since deleted): the awaiter got `CancelledError` immediately while
        the thread body ran to the end, and an exception the body raised after that was
        swallowed with no "never retrieved" warning at all. So the task is kept and given a
        done-callback instead — that callback is the only thing that ever hears from an
        abandoned tool again.
        """
        task = asyncio.ensure_future(asyncio.to_thread(self._execute_sync, tool_call))
        cancel_wait = asyncio.ensure_future(self._cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_wait in done and not cancel_wait.cancelled():
                failure = cancel_wait.exception()
                if failure is not None:
                    # The Stop wait FAILING is not the user pressing Stop — the 2026-09-18
                    # defence. Read as one, it would throw away the result of a tool
                    # nobody stopped. The RESOLUTION here is deliberately not
                    # `_interruptible`'s, which cancels the task and re-raises: re-raising
                    # would come out of `_handle_tool_calls` with this call already
                    # announced and no tool result written, i.e. the orphaned tool_call
                    # this file exists to prevent. Falling back instead to the behaviour
                    # that needs no stop signal at all — wait the tool out, as before this
                    # change — costs only the latency the failure was going to cost anyway.
                    logger.warning(
                        "session %s: the stop signal failed while %s was running (%s: %s);"
                        " waiting for the tool instead of abandoning it",
                        self.audit_context.get("session_id") or "-",
                        tool_call.name,
                        type(failure).__name__,
                        failure,
                    )
                    return await task
            # The tool winning outranks Stop landing in the same pass: a finished call has
            # a real result and there is nothing to gain from discarding it.
            if task in done:
                return task.result()
            self._abandon_tool_wait(tool_call, task)
            return None
        finally:
            cancel_wait.cancel()

    def _abandon_tool_wait(self, tool_call: ToolCall, task: "asyncio.Future") -> None:
        """Let go of `task`: nothing will read its result, and the only trace the thread
        leaves when it finally finishes is a log line plus an audit record.

        The done-callback must NOT touch conversation state. By the time it runs the turn
        has ended, `_abandoned_tool` has already written this call's tool result, and a
        late `_record_result` would append a SECOND result for the same tool_call_id (and
        record artifacts for a call the user stopped).

        It also fires in a shape where the thread is NOT over, so nothing below may assume
        it is. A loop shutting down with this task still pending CANCELS it first:
        `explore`'s runner cancels every leftover task and gathers them on the still-live
        loop before closing it (`_cancel_leftover_tasks`, tools/subagent.py). Measured
        2026-09-22 on this branch (scratchpad probe, since deleted; pinned by
        `test_a_torn_down_abandoned_tool_is_not_logged_as_finished`): the callback ran
        during that teardown with `fut.cancelled()` true, and the tool body went on for
        another second. Corrected here, because the branch's first version of this
        docstring said a closed loop covered that case — it does not, cancellation gets
        there first. Three consequences, accepted rather than fixed: the live counter is
        given back early, the elapsed time stops at the cancellation instead of at the
        thread's end, and `_tool_started_at` may be popped before the thread stamps it.

        A loop that is already CLOSED is the third shape and runs no callback at all
        (`asyncio.futures._call_set_state` returns early on `dest_loop.is_closed()` — read
        in this venv's CPython 3.13); there the counter is never given back. Between them
        that is why the whole body is wrapped and why the counter is only an indication.
        """
        session = self.audit_context.get("session_id") or "-"
        started = self._tool_started_at.get(tool_call.id)
        global _abandoned_live, _abandoned_warned
        pool = _default_thread_pool_size()
        with _abandoned_lock:
            _abandoned_live += 1
            live = _abandoned_live
            warn_pressure = not _abandoned_warned and live > pool // 2
            if warn_pressure:
                _abandoned_warned = True
        if warn_pressure:
            # Naming the consequence, because the symptom it produces is unreadable
            # otherwise. That pool is not only the tool pool: `_astream` submits the
            # provider's stream producer to the SAME default executor
            # (`loop.run_in_executor(None, produce)`), so a saturated pool delays the next
            # MODEL call, not just the next tool — and the first-chunk clock does not
            # start until the producer is actually running, which is what
            # `first_chunk_deadline_waiting_on_executor` logs.
            logger.warning(
                "%d tool threads are running with nobody waiting for them; the default "
                "thread pool holds %d and the provider's stream producer shares it, so "
                "further work — including the next model call — may queue behind them",
                live,
                pool,
            )

        def _finished(fut: "asyncio.Future") -> None:
            try:
                global _abandoned_live, _abandoned_warned
                with _abandoned_lock:
                    _abandoned_live -= 1
                    if _abandoned_live <= 0:
                        # Re-arm. The warning is about a BURST of abandoned threads; a
                        # one-shot that is never reset would report the first burst in the
                        # life of the process and stay silent through every later one.
                        _abandoned_warned = False
                detail = _abandoned_outcome(fut)
                elapsed = (time.time() - started) if started is not None else None
                age = f"{elapsed:.1f}s" if elapsed is not None else "an unknown time"
                if fut.cancelled():
                    # The loop is being torn down under a thread that is still running.
                    # Saying "finished" here would be false, and `age` measures only up to
                    # the cancellation.
                    logger.warning(
                        "session %s: abandoned tool %s was let go %s in, with its thread "
                        "still running; whatever it returns is discarded unread",
                        session,
                        tool_call.name,
                        age,
                    )
                    reason = "let go while still running; its loop was shutting down"
                else:
                    logger.warning(
                        "session %s: abandoned tool %s finished after %s with nobody "
                        "waiting; its result (%s) was discarded",
                        session,
                        tool_call.name,
                        age,
                        detail,
                    )
                    reason = f"finished after the turn stopped waiting; {detail}"
                self._audit(
                    tool_call,
                    stage="abandoned_exit",
                    status="abandoned",
                    reason=reason,
                )
                # `_execute_sync` stamps `_tool_started_at` from inside the thread, so the
                # stamp can land AFTER `_abandoned_tool` popped it. Where the tool really
                # finished, this is the pop guaranteed to find it; on the cancelled path
                # the thread may stamp it after this runs, and that one entry is left
                # behind on an engine that is being torn down with its loop anyway.
                self._tool_started_at.pop(tool_call.id, None)
            except Exception:  # pragma: no cover - a callback must never raise on the loop
                pass

        task.add_done_callback(_finished)

    def _abandoned_tool(self, tool_call: ToolCall) -> Event:
        """The stop-path answer for a call whose thread we stopped waiting for.

        `executed: true` is the load-bearing field. The tool very likely DID run (and may
        still be running); a plain "not executed" here would invite the model to re-run a
        call that already happened the moment the conversation continues.
        """
        result = {
            "error": "tool result unavailable",
            "reason": (
                "stopped waiting for the tool; it may have completed after the stop"
            ),
            "executed": True,
        }
        self.messages.append(_tool_result_message(tool_call, result))
        # Same side tables `_record_result` clears, cleared here for the same reason: they
        # are keyed by tool_call.id and nothing else will ever come back for this one.
        self._approval_origins.pop(tool_call.id, None)
        self._standing_notes.pop(tool_call.id, None)
        self._tool_started_at.pop(tool_call.id, None)
        self._audit(
            tool_call,
            stage="finished",
            status="abandoned",
            reason="stopped waiting for the tool",
        )
        return Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": "abandoned",
                "reason": "stopped waiting",
                "result_preview": _preview(result),
            },
        )

    def _mangled_tool(self, tool_call: ToolCall) -> Event:
        """Answer a tool call whose arguments never parsed, with the real diagnosis.

        Two causes, two different cures — and the model can only pick the right one if
        the error says which happened. Truncation (`finish_reason == "length"`) means
        "same content, smaller pieces"; plain bad JSON means "re-send with the declared
        parameters". Either way the raw text is NOT replayed into history: a stored
        `{"_raw": …}` call reads as a worked example and teaches the model to emit
        `_raw` on purpose (observed 2026-08-15), on top of re-sending the junk tokens
        every turn."""
        if self._turn_truncated:
            reason = (
                "your tool-call arguments were cut off by the output-token limit before "
                "they finished streaming — the tool never received them. Produce the same "
                "content in smaller pieces: several calls that each write or append a "
                "section, keeping each call's content well under the limit. Do not retry "
                "the identical oversized call."
            )
        else:
            reason = (
                "your tool-call arguments did not parse as a JSON object, so the tool "
                "received nothing. `_raw` is not a parameter — it is the unparsed text of "
                "the failed call. Re-issue the call using the tool's declared parameters."
            )
        self.messages.append(_tool_error_message(tool_call, reason))
        self._audit(tool_call, stage="finished", status="error", reason=reason)
        return Event(
            EventType.TOOL_FINISHED,
            {"name": tool_call.name, "status": "error", "reason": reason},
        )

    def _interrupted_tool(self, tool_call: ToolCall) -> Event:
        """The stop-path answer for a call that will not run: a tool-error result in the
        history (hosted chat templates reject orphaned tool_calls, and durable-resume
        would otherwise re-prompt it) + the finished event for the tool card."""
        self.messages.append(_tool_error_message(tool_call, "interrupted by user"))
        self._audit(
            tool_call, stage="finished", status="interrupted", reason="user stop"
        )
        return Event(
            EventType.TOOL_FINISHED,
            {"name": tool_call.name, "status": "interrupted", "reason": "stopped"},
        )

    def _parallel_safe(self, tool_call: ToolCall) -> bool:
        # Only metadata-declared low-risk tools (reads, searches, git queries) run
        # concurrently; writes, shell, and anything unannotated stay strictly ordered.
        spec = self.registry.get(tool_call.name)
        metadata = spec.metadata if spec else None
        return getattr(metadata, "risk_level", "") == "low" and not getattr(
            metadata, "requires_approval", False
        )

    # -- Auto-Approve reviewer (spec Part 8) ----------------------------------------

    def _reviewer_active(self) -> bool:
        """The reviewer is consulted only when ALL of these hold. Any miss ⇒ today's
        behaviour (the card). Attended is required explicitly: `is_attended` unset counts
        as NOT attended, so automations — which never set it — can never be reviewed
        (§1.5: the mode is attended-only)."""
        from .permissions import Mode

        return (
            self.reviewer is not None
            and self.permissions.mode is Mode.AUTO_APPROVE
            and self.is_attended is not None
            and self.is_attended()
            and self._reviewer_denials < _REVIEWER_TRIP
        )

    def _user_history(self) -> tuple[str, list[dict[str, Any]]]:
        """(current request, earlier user messages) — the user's own words only, extracted
        mechanically (§8.2). Never agent output, never tool results, never a summary.

        `ask_user` answers are merged in from `_ask_replies` (captured as they arrived, not
        parsed out of tool envelopes), tagged `is_reply` so `render_history` prints the
        "[reply to a question the agent asked]" marker the §8.3 instructions already know
        how to weigh. A reply is always HISTORY, never the current request — "ok proceed"
        must not become the headline the action is judged against.

        Attachments collapse to neutral markers via `reviewer_text` (§4.4): the reviewer
        learns a file was attached, never what it says — an attachment body is
        outside-authored text riding a user turn."""
        from .attachments import reviewer_text

        texts: list[str] = []
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            text = reviewer_text(msg.get("content"))
            if text:
                texts.append(text)
        if not texts:
            return "", [
                {"text": t, "is_reply": True, **({"question": q} if q else {})}
                for _, t, q in self._ask_replies
            ]
        history: list[dict[str, Any]] = []
        for i, t in enumerate(texts[:-1], start=1):
            history.append({"text": t})
            history.extend(
                {"text": r, "is_reply": True, **({"question": q} if q else {})}
                for a, r, q in self._ask_replies
                if a == i
            )
        # Replies captured during the current turn (anchor == len(texts)) — or after an
        # anchor message that was itself empty/skipped — land at the tail, so a same-turn
        # consent is already visible to the reviewer for the very next action.
        history.extend(
            {"text": r, "is_reply": True, **({"question": q} if q else {})}
            for a, r, q in self._ask_replies
            if a >= len(texts)
        )
        return texts[-1], history

    def _downloaded_target(self, tool_call: ToolCall) -> Optional[Any]:
        """A file this call would run that the agent DOWNLOADED this session, or None.
        Fetch-then-execute has no quiet legitimate form, so it reaches a person over both
        the reviewer and any command allowlist (OPE-114 §1)."""
        match = self._agent_files.match(
            tool_call.name, tool_call.arguments, step=self._step
        )
        return match if match is not None and match.downloaded else None

    def _provenance(self, tool_call: ToolCall) -> str:
        """One line naming a file this call would run that the agent itself created, or ""
        (§8.2). Fixed vocabulary — never file contents, never outside-authored text, so the
        no-untrusted-content rule holds."""
        match = self._agent_files.match(
            tool_call.name, tool_call.arguments, step=self._step
        )
        return match.render() if match else ""

    async def _preconsult_reviewer(self, tool_calls: list[ToolCall]) -> None:
        """Fire one reviewer request per call that will escalate, all concurrently, and
        park the verdicts for `_authorize` to consume. One action per request — there is
        no verdict list to pair back, so a verdict cannot land on the wrong action (§8.6).
        Skips calls the gate already decides (allow or hard-deny): the reviewer only ever
        sees what would otherwise become an approval card (§1.2)."""
        if not self._reviewer_active() or not tool_calls:
            return
        interactive = {"request_directory", "propose_plan", "ask_user"}
        pending: list[ToolCall] = []
        for tool_call in tool_calls:
            if tool_call.name in interactive or tool_call.id in self._reviewer_verdicts:
                continue
            spec = self.registry.get(tool_call.name)
            if spec is None:
                continue
            decision = self.permissions.evaluate(
                tool_call.name, tool_call.arguments, spec.metadata
            )
            # human_only asks never reach the reviewer — same rule as `_authorize`.
            if (
                not decision.allowed
                and decision.needs_user
                and not decision.human_only
                and self._downloaded_target(tool_call) is None
            ):
                pending.append(tool_call)
        if not pending:
            return
        request, history = self._user_history()
        verdicts = await asyncio.gather(
            *[
                self.reviewer.review(
                    request=request,
                    history=history,
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    provenance=self._provenance(tc),
                )
                for tc in pending
            ]
        )
        for tc, verdict in zip(pending, verdicts):
            self._reviewer_verdicts[tc.id] = verdict

    async def _consult_reviewer(self, tool_call: ToolCall) -> Any:
        """The parked verdict from `_preconsult_reviewer`, or a fresh single call."""
        verdict = self._reviewer_verdicts.pop(tool_call.id, None)
        if verdict is not None:
            return verdict
        request, history = self._user_history()
        return await self.reviewer.review(
            request=request,
            history=history,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            provenance=self._provenance(tool_call),
        )

    @staticmethod
    def _action_key(tool_name: str, arguments: dict[str, Any] | None) -> tuple[str, str]:
        try:
            canon = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            canon = str(arguments)
        return (tool_name, canon)

    def approve_action_once(self, tool_name: str, arguments: dict[str, Any] | None) -> None:
        """Register a one-shot human approval for this EXACT action (§8.4 "Allow anyway").

        Called by the server when the user clicks the deny card — a human decision made
        with the full reviewer reason in front of them. The next proposal of the identical
        action (same tool, byte-identical canonical arguments) runs without the reviewer or
        a card; anything that differs at all still goes through the normal flow. Never
        standing: consumed on first use."""
        self._allow_anyway.add(self._action_key(tool_name, arguments))
        if self.audit_sink is not None:
            try:
                self.audit_sink(
                    {
                        **self.audit_context,
                        "tool": tool_name,
                        "arguments": arguments or {},
                        "stage": "allow_anyway_granted",
                        "status": "granted",
                        "reason": "user approved via the deny card (one-shot, exact action)",
                    }
                )
            except Exception:
                pass

    def _consume_allow_anyway(self, tool_call: ToolCall) -> bool:
        key = self._action_key(tool_call.name, tool_call.arguments)
        if key in self._allow_anyway:
            self._allow_anyway.discard(key)
            return True
        return False

    def _spawn_shadow_review(self, tool_call: ToolCall) -> None:
        """Shadow evaluation (spec Part 6 step 3): record what the reviewer WOULD have
        decided about this card, without touching anything. Fire-and-forget — the card
        renders immediately; the verdict lands in the audit log when the call returns,
        joined to the human's `approval_resolved` row by `call_id`. There is deliberately
        no code path from a shadow verdict to a decision."""
        if self.reviewer is None or not self.reviewer_shadow:
            return
        request, history = self._user_history()
        prov = self._provenance(tool_call)

        async def _shadow() -> None:
            try:
                verdict = await self.reviewer.review(
                    request=request,
                    history=history,
                    provenance=prov,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                )
                self._audit(
                    tool_call,
                    stage="reviewer_shadow",
                    status=verdict.verdict,
                    reason=verdict.reason,
                    call_id=tool_call.id,
                    tokens_in=verdict.tokens_in,
                    tokens_out=verdict.tokens_out,
                    cache_read=verdict.cache_read,
                    cache_write=verdict.cache_write,
                )
            except Exception:
                pass  # shadow must never surface a failure

        spawn_retained(self._shadow_tasks, _shadow())

    async def drain_shadow_reviews(self) -> None:
        """Await in-flight shadow verdicts (tests and orderly shutdown; never the hot path)."""
        if self._shadow_tasks:
            await asyncio.gather(*list(self._shadow_tasks), return_exceptions=True)

    async def _authorize(self, tool_call: ToolCall) -> "AsyncIterator[Event | bool]":
        """Permission flow for one call (TOOL_PROPOSED is emitted by the caller). Yields
        its events, then True/False (allowed) last. Denied/unknown calls get their
        tool-error message appended here."""
        from .permissions import standing_rule_candidate

        spec = self.registry.get(tool_call.name)
        metadata = spec.metadata if spec else None

        decision = self.permissions.evaluate(
            tool_call.name, tool_call.arguments, metadata
        )
        allowed = decision.allowed
        reason = decision.reason

        # OPE-114 §1: running something the agent DOWNLOADED this session is the classic
        # fetch-then-execute chain, and there is no quiet legitimate version of it — so it
        # goes to a person, over both the reviewer and any command allowlist that would
        # otherwise wave it through (a `python` prefix rule must not vouch for a script
        # pulled off the internet a moment ago). A hard deny is left untouched: this floor
        # only ever tightens an allow, never loosens a block. Agent-WRITTEN files are not
        # floored — "write this script and run it" is ordinary work — they travel as a fact
        # for the reviewer to weigh instead.
        provenance_note = self._provenance(tool_call)
        if self._downloaded_target(tool_call) is not None and (
            decision.needs_user or allowed
        ):
            allowed = False
            reason = f"this file was downloaded by the agent this session — {provenance_note}"
            decision = replace(
                decision,
                allowed=False,
                reason=reason,
                needs_user=True,
                human_only=True,
            )

        if allowed and decision.rule:
            # A task-scoped standing rule auto-allowed this call: audit the exact rule
            # (§25 invariant — every auto-allowed call cites its rule) and remember it so
            # the tool card can say "allowed by standing rule".
            self._standing_notes[tool_call.id] = decision.rule
            self._audit(
                tool_call, stage="auto_allowed", status="allowed", reason=reason
            )

        # (c) Bypass mode ran a consequential call no other rule allowed: annotate it.
        # "full access" is the exact reason string of permissions.py's bypass branch.
        if allowed and decision.reason == "full access":
            self._approval_origins[tool_call.id] = {"origin": "bypass"}

        if not allowed and decision.needs_user and self._consume_allow_anyway(tool_call):
            # §8.4 "Allow anyway": the human already approved this exact action from the
            # deny card. One-shot — consumed above; a different action never matches.
            allowed = True
            reason = "approved by user (allow anyway)"
            self._audit(tool_call, stage="auto_allowed", status="allowed", reason=reason)

        consulted_live = False
        unsure_note = ""  # the reviewer's hesitation, when an unsure verdict raised the card
        if (
            not allowed
            and decision.needs_user
            and not decision.human_only
            and self._reviewer_active()
        ):
            # The one thing the reviewer may do: turn "ask the human" into "go ahead" —
            # never "blocked" into "go ahead" (§1.2; hard denies never reach this branch
            # because needs_user is False on them). `human_only` asks (git hooks, CI
            # configs, unscopable writes) skip the reviewer entirely: their floor is that
            # a PERSON sees them, and a verdict here would be that floor's bypass.
            consulted_live = True
            verdict = await self._consult_reviewer(tool_call)
            self._audit(
                tool_call,
                stage="reviewer_verdict",
                status=verdict.verdict,
                reason=verdict.reason,
                tokens_in=verdict.tokens_in,
                tokens_out=verdict.tokens_out,
                cache_read=verdict.cache_read,
                cache_write=verdict.cache_write,
            )
            if verdict.verdict == "allow":
                allowed = True
                self._reviewer_denials = 0  # streak semantics: any non-deny resets
                self._approval_origins[tool_call.id] = {
                    "origin": "reviewer", "note": verdict.reason
                }
                reason = f"allowed by reviewer: {verdict.reason}"
            elif verdict.verdict == "deny":
                # §8.4 deny asymmetry — full reason to the USER (event + audit above),
                # terse non-diagnostic refusal to the AGENT. The sanctioned way around a
                # deny is ask the human, never reshape the request.
                from .reviewer import AGENT_DENY_MESSAGE

                self._reviewer_denials += 1
                tripped = self._reviewer_denials == _REVIEWER_TRIP
                if tripped:
                    # (a) The breaker must never trip silently (owner catch 2026-08-24):
                    # persist a notice so reloads see it too.
                    self._append_notice("reviewer_paused", _REVIEWER_PAUSED_TEXT)
                yield Event(
                    EventType.TOOL_FINISHED,
                    {
                        "name": tool_call.name,
                        "status": "denied",
                        "reason": "blocked by the safety reviewer",
                        "reviewer_reason": verdict.reason,
                        "allow_anyway": True,
                        **({"reviewer_paused": _REVIEWER_PAUSED_TEXT} if tripped else {}),
                    },
                )
                deny_msg = _tool_error_message(tool_call, AGENT_DENY_MESSAGE)
                deny_msg["_display"] = {
                    "approval_origin": "reviewer_denied",
                    "approval_note": verdict.reason,
                }
                self.messages.append(deny_msg)
                self._audit(
                    tool_call,
                    stage="finished",
                    status="denied",
                    reason=f"denied by reviewer: {verdict.reason}",
                )
                yield False
                return
            # "unsure" falls through to today's card — the human decides.
            if verdict.verdict == "unsure":
                self._reviewer_denials = 0  # streak semantics: any non-deny resets
                unsure_note = verdict.reason

        if not allowed and decision.needs_user:
            # Shadow evaluation: record what the reviewer would have said about this card.
            # Skipped when the live path already consulted it (an `unsure` falling through
            # to the card is already audited as reviewer_verdict — no double spend).
            if not consulted_live:
                self._spawn_shadow_review(tool_call)
            yield Event(
                EventType.PERMISSION_REQUIRED,
                {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "reason": decision.reason,
                    # An `unsure` verdict raised this card: the reviewer's one-line reason
                    # answers "why am I being asked?" in place (owner ask 2026-08-24).
                    **(
                        {"reviewer_unsure": verdict.reason}
                        if consulted_live and verdict.verdict == "unsure"
                        else {}
                    ),
                    "category": getattr(metadata, "category", ""),
                    # The exact target a standing rule could pin, or None when the call
                    # isn't eligible (no declared target arg / exec risk). Surfaces use it
                    # to offer "Allow every time" on automation-run approval cards only.
                    # OPE-114 §1: the fact neither the reviewer nor the human could get
                    # from the command text alone.
                    "provenance": provenance_note,
                    "standing_target": standing_rule_candidate(
                        tool_call.name,
                        tool_call.arguments,
                        metadata,
                        self.permissions.risk_overrides,
                    ),
                    # True when this shell command classifies as read-only — the card
                    # offers "Allow read-only commands for this session" only then.
                    "readonly_ok": _readonly_ok(tool_call.arguments),
                    **(
                        self.approval_extras(tool_call.name, tool_call.arguments)
                        if self.approval_extras
                        else {}
                    ),
                },
            )
            self._audit(
                tool_call,
                stage="approval_requested",
                reason=decision.reason,
                call_id=tool_call.id,
            )
            outcome = await self._interruptible(
                self.approver(
                    PermissionRequest(
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        metadata=metadata,
                        reason=decision.reason,
                        tool_call_id=tool_call.id,
                    )
                ),
                interrupted=ApprovalOutcome.DENY,
            )
            if outcome is ApprovalOutcome.DENY:
                allowed, reason = (
                    False,
                    "interrupted by user" if self._cancel.is_set() else "denied by user",
                )
                self._approval_origins[tool_call.id] = {
                    "origin": "user",
                    "grant": "deny",
                    **({"note": unsure_note} if unsure_note else {}),
                }
                self._audit(
                    tool_call,
                    stage="approval_resolved",
                    call_id=tool_call.id,
                    status="denied",
                    approval=outcome.value,
                    reason=reason,
                )
            else:
                if outcome is ApprovalOutcome.ALWAYS_TOOL:
                    self.permissions.allow_tool_for_session(tool_call.name)
                elif outcome is ApprovalOutcome.ALWAYS_COMMAND:
                    self.permissions.allow_command_for_session(
                        str(tool_call.arguments.get("command", ""))
                    )
                elif outcome is ApprovalOutcome.ALWAYS_DOMAIN:
                    self.permissions.allow_domain_for_session(
                        str(tool_call.arguments.get("url", ""))
                    )
                elif outcome is ApprovalOutcome.READONLY_SESSION:
                    self.permissions.allow_readonly_for_session()
                allowed, reason = True, "approved by user"
                self._approval_origins[tool_call.id] = {
                    "origin": "user",
                    "grant": outcome.value,
                    **({"note": unsure_note} if unsure_note else {}),
                }
                self._audit(
                    tool_call,
                    stage="approval_resolved",
                    call_id=tool_call.id,
                    status="approved",
                    approval=outcome.value,
                    reason=reason,
                )

        if not allowed:
            if spec is None:
                reason = f"unknown tool: {tool_call.name}"
            err_msg = _tool_error_message(tool_call, reason)
            origin = self._approval_origins.pop(tool_call.id, None)
            if origin:
                err_msg["_display"] = {
                    "approval_origin": origin.get("origin", ""),
                    **({"approval_note": origin["note"]} if origin.get("note") else {}),
                    **({"approval_grant": origin["grant"]} if origin.get("grant") else {}),
                }
            self.messages.append(err_msg)
            yield Event(
                EventType.TOOL_FINISHED,
                {"name": tool_call.name, "status": "denied", "reason": reason},
            )
            self._audit(tool_call, stage="finished", status="denied", reason=reason)
            yield False
            return

        if spec is None:
            self.messages.append(
                _tool_error_message(tool_call, f"unknown tool: {tool_call.name}")
            )
            yield Event(
                EventType.TOOL_FINISHED,
                {"name": tool_call.name, "status": "error", "reason": "unknown tool"},
            )
            yield False
            return

        yield True

    def _execute_sync(self, tool_call: ToolCall) -> tuple[Any, str]:
        """Execute one authorized call (runs in a worker thread)."""
        # The one chokepoint every executed call passes through, concurrent or serial.
        self._tool_started_at[tool_call.id] = time.time()
        try:
            return self.registry.execute(tool_call.name, tool_call.arguments), "ok"
        except Exception as exc:
            # A tool may answer "the tool for this is X" — `write_file` refusing a .xlsx is
            # the case this exists for (tools/files.py). Materialising X here means the
            # model FINDS it: `_astream` re-reads registry.schemas() every round trip, so
            # the very next one carries it, whether or not the model thought to call the
            # `load_*` meta-tool the refusal text names. A tool function cannot do this
            # itself — the registry does not exist yet when AgentContext is built.
            #
            # Deliberately after nothing and before nothing: the error the model sees is
            # unchanged (same message, same `error_type`), and a loader that blows up must
            # not replace a precise refusal with a confusing one.
            for name in getattr(exc, "materialize_tools", None) or ():
                try:
                    self.registry.get(str(name))
                except Exception:  # pragma: no cover - never mask the real error
                    pass
            return {"error": str(exc), "error_type": type(exc).__name__}, "error"

    def _record_result(self, tool_call: ToolCall, result: Any, status: str) -> Event:
        self._step += 1
        if status == "ok":
            # Only successful calls: a write that raised left nothing on disk to run.
            self._agent_files.record(
                tool_call.name, tool_call.arguments, result, step=self._step
            )
        # A `_display` key on a tool result is user-facing metadata the AGENT must
        # never see (e.g. how many gmail hits the privacy filters hid — a count
        # the model could probe around). Lift it onto the message as a sidecar
        # (like `source`), stripped from every provider feed in
        # `_outbound_messages` but persisted for the GUI's tool card.
        display: Optional[dict[str, Any]] = None
        if isinstance(result, dict) and "_display" in result:
            display = result.get("_display") or None
            result = {k: v for k, v in result.items() if k != "_display"}
        origin = self._approval_origins.pop(tool_call.id, None)
        if origin:
            # Provenance survives reload via the same display-only sidecar as the privacy
            # counts (owner ruling 2026-08-24) — `_outbound_messages` strips it, so no
            # provider ever sees it.
            display = {
                **(display or {}),
                "approval_origin": origin.get("origin", ""),
                **({"approval_note": origin["note"]} if origin.get("note") else {}),
                **({"approval_grant": origin["grant"]} if origin.get("grant") else {}),
            }
        message = _tool_result_message(tool_call, result)
        if display:
            message["_display"] = display
        started = self._tool_started_at.pop(tool_call.id, None)
        if started is not None:
            # Display/derivation-only sidecar like `ts`: stripped from every provider feed
            # in `_outbound_messages`, kept in the jsonl. With `ts` it brackets exactly the
            # interval the tool was running in.
            message["t0"] = started
        self.messages.append(message)
        hidden = int((display or {}).get("hidden_by_filters") or 0)
        stripped = int((display or {}).get("hidden_fields") or 0)
        if hidden or stripped:
            # The out-of-band trace the user CAN see: rule class + count, never content.
            parts = []
            if hidden:
                parts.append(f"{hidden} result(s) hidden")
            if stripped:
                parts.append(f"{stripped} field value(s) stripped")
            self._audit(
                tool_call,
                stage="filtered",
                status="hidden",
                reason=" · ".join(parts) + " by privacy filters",
            )
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        self._note_ingestion(tool_call, status)
        rule = self._standing_notes.pop(tool_call.id, "")
        return Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
                **({"display": display} if display else {}),
                **({"standing_rule": rule} if rule else {}),
                # (c) quiet provenance chip — same fields the `_display` sidecar persists.
                **(
                    {
                        "approval_origin": origin.get("origin", ""),
                        **({"approval_note": origin["note"]} if origin.get("note") else {}),
                        **({"approval_grant": origin["grant"]} if origin.get("grant") else {}),
                    }
                    if origin
                    else {}
                ),
            },
        )

    def _note_ingestion(self, tool_call: ToolCall, status: str) -> None:
        """Record that outside content entered this session, and from where. The fact and
        the source only — never the content, not even truncated.

        **Nothing consumes this in v1.** It exists so that when the reviewer is eventually
        offered the fact (v2, `PRV-1`), the question "would it have changed a verdict?" can
        be answered by replaying a shadow run instead of re-argued. See
        `session_facts.py` and the spec's Part 0.

        Failed calls are skipped: a fetch that errored brought nothing in.
        """
        if self.session_facts is None or status != "ok":
            return
        spec = self.registry.get(tool_call.name)
        if not session_facts.is_ingesting(spec.metadata if spec else None):
            return
        record = self.session_facts.note(tool_call.name, tool_call.arguments)
        self._audit(tool_call, **record.to_audit())

    def _audit(self, tool_call: ToolCall, **event: Any) -> None:
        if self.audit_sink is None:
            return
        payload = {
            **self.audit_context,
            "tool": tool_call.name,
            "arguments": tool_call.arguments,
            **event,
        }
        try:
            self.audit_sink(payload)
        except Exception:
            pass

    async def _handle_items_proposal(self, tool_call: ToolCall) -> AsyncIterator[Event]:
        """The decomposition gate: emit the proposed items, await the user's decision.
        Approval creates them on the board (server-side, inside the approver) and the
        result carries their ids; rejection returns feedback for a revised split."""
        args = tool_call.arguments or {}
        items = args.get("items") or []
        valid = [
            i
            for i in items
            if isinstance(i, dict)
            and str(i.get("title", "")).strip()
            and str(i.get("criteria", "")).strip()
        ]
        if not valid or len(valid) != len(items):
            result: dict[str, Any] = {
                "approved": False,
                "error": "every proposed item needs a title and acceptance criteria",
            }
        elif self.items_approver is None:
            result = {
                "approved": False,
                "error": "item proposals aren't available in this surface",
            }
        else:
            yield Event(
                EventType.ITEMS_PROPOSED,
                {"items": valid, "note": str(args.get("note", ""))},
            )
            self._audit(tool_call, stage="items_proposed")
            result = await self._interruptible(
                self.items_approver(dict(args), tool_call.id),
                interrupted={"approved": False, "error": "interrupted by user"},
            ) or {"approved": False, "error": "no response"}

        status = "ok" if result.get("approved") else "denied"
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    async def _handle_team_proposal(self, tool_call: ToolCall) -> AsyncIterator[Event]:
        """The staffing gate: emit the proposed roster, await the user's out-of-band
        decision. Approval PRE-SPAWNS the worker sessions (server-side, inside the
        approver) and the result carries the roster with actor ids so the lead can
        assign; rejection returns the user's feedback for a revised proposal."""
        args = tool_call.arguments or {}
        members = args.get("members") or []
        if not isinstance(members, list) or not members:
            result: dict[str, Any] = {
                "approved": False,
                "error": "propose at least one member ({persona, model?, reason?})",
            }
        elif self.team_approver is None:
            result = {
                "approved": False,
                "error": "team staffing isn't available in this surface",
            }
        else:
            yield Event(
                EventType.TEAM_PROPOSED,
                {
                    "members": members,
                    "enable_chat": bool(args.get("enable_chat", False)),
                    "note": str(args.get("note", "")),
                },
            )
            self._audit(tool_call, stage="team_proposed")
            result = await self._interruptible(
                self.team_approver(dict(args), tool_call.id),
                interrupted={"approved": False, "error": "interrupted by user"},
            ) or {"approved": False, "error": "no response"}

        status = "ok" if result.get("approved") else "denied"
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    async def _handle_plan_proposal(self, tool_call: ToolCall) -> AsyncIterator[Event]:
        """Emit the plan for review, await the user's out-of-band decision, and apply it:
        approval flips the live PermissionEngine out of plan mode (the same session keeps
        going, with all its exploration context); rejection keeps plan mode and returns
        the user's feedback so the agent can revise."""
        args = tool_call.arguments or {}
        plan = str(args.get("plan", ""))
        if self.permissions.mode is not Mode.PLAN:
            # The tool is always registered (mode can flip mid-session), but proposing a
            # plan only means something while the session is actually in plan mode. The
            # right next step differs by mode: discuss stays read-only, so the agent
            # should talk through the change; write-capable modes should just do it.
            if self.permissions.mode is Mode.DISCUSS:
                error = (
                    "not in plan mode — this is discuss mode (read-only), so describe "
                    "the proposed changes in chat instead"
                )
            else:
                error = "not in plan mode — proceed with the work directly"
            result: dict[str, Any] = {"approved": False, "error": error}
        elif self.plan_approver is None:
            result = {
                "approved": False,
                "error": "plan approval isn't available here",
            }
        else:
            yield Event(EventType.PLAN_PROPOSED, {"plan": plan})
            self._audit(tool_call, stage="plan_proposed")
            result = await self._interruptible(
                self.plan_approver(dict(args), tool_call.id),
                interrupted={"approved": False, "error": "interrupted by user"},
            ) or {
                "approved": False,
                "error": "no response",
            }

        if result.get("approved"):
            # The approver may pick the post-plan mode ("interactive" asks per write,
            # "auto" executes the approved plan without further prompts).
            try:
                self.permissions.mode = Mode(str(result.get("mode", "interactive")))
            except ValueError:
                self.permissions.mode = Mode.INTERACTIVE
            result = {
                **result,
                "mode": self.permissions.mode.value,
                "note": "plan approved — implement it now",
            }

        status = "ok" if result.get("approved") else "denied"
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    async def _handle_tool_request(self, tool_call: ToolCall) -> AsyncIterator[Event]:
        """Emit the install prompt, await the user's decision, hand the outcome back.

        Declining is a normal outcome, not an error: the result tells the agent to fall back
        and disclose the gap, because a security report that quietly loses a check is worse
        than one that says which checks it couldn't run.
        """
        args = tool_call.arguments or {}
        name = str(args.get("name", "")).strip()
        reason = str(args.get("reason", ""))

        if self.tool_requester is None or not name:
            result: dict[str, Any] = {
                "installed": False,
                "error": "tool requests aren't available here",
                "guidance": (
                    "Continue without it: use a fallback check if you have one, and say in "
                    "your report which checks were degraded."
                ),
            }
        elif name not in _toolchain.MANAGED:
            # Not in the pinned catalog: no card at all (owner-hit 2026-08-20 — agents
            # routed ordinary brew/pip installs through the install card, which could
            # only fail after approval). The agent has a shell with its own approval
            # flow; steer it there instead of at the user.
            #
            # NOTE: this is catalog membership, not `describe(name) is None` — a tool can
            # be a pinned catalog member with no build for THIS platform (e.g. gitleaks on
            # Windows today). That still deserves a card, just one whose `installable` is
            # False; only a name outside the catalog entirely skips the card.
            catalog = ", ".join(sorted(_toolchain.MANAGED))
            result = {
                "installed": False,
                "error": (
                    f"'{name}' is not in the pinned tool catalog ({catalog})."
                ),
                "guidance": (
                    "Install it yourself with the shell (brew/pip/…, subject to the "
                    "normal command approval), or continue without it and say in your "
                    "report which checks were degraded."
                ),
            }
        else:
            # The prompt must say up front whether WE can install this (pinned build for
            # this platform) — a card that offers Install for a tool we can't fetch turns
            # the user's approval into a guaranteed error. Absence of metadata means NO.
            info = _toolchain.describe(name)
            yield Event(
                EventType.TOOL_REQUESTED,
                {
                    "name": name,
                    "reason": reason,
                    "installable": info is not None,
                    "version": (info or {}).get("version", ""),
                    "summary": (info or {}).get("summary", ""),
                    "source": (info or {}).get("source", ""),
                },
            )
            self._audit(tool_call, stage="tool_requested", reason=reason)
            result = await self._interruptible(
                self.tool_requester(dict(args), tool_call.id),
                interrupted={"installed": False, "error": "interrupted by user"},
            ) or {"installed": False, "error": "no response"}
            if not result.get("installed"):
                # The card says "or install it yourself and continue" — honor it. A user
                # who brewed the tool mid-prompt and clicked Continue has PROVIDED it,
                # not declined it; find their copy before treating this as a refusal.
                found = _toolchain.resolve(name)
                if found:
                    result = {
                        "installed": True,
                        "path": found,
                        "note": (
                            "the user provided their own copy instead of the managed "
                            "install — use it from this path"
                        ),
                    }
            if not result.get("installed"):
                result.setdefault(
                    "guidance",
                    "Continue without it: use a fallback check if you have one, and say in "
                    "your report which checks were degraded.",
                )

        status = "ok" if result.get("installed") else "denied"
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    def _already_granted(self, args: dict[str, Any]) -> Optional[dict[str, Any]]:
        """The request restated as a grant when the session ALREADY holds the folder — the
        named path is a directory inside one of `roots`, with at least the access asked for.

        The loop this closes (owner-hit 2026-08-31): a consumer that had gone stale on the
        roots list kept refusing a folder the user HAD granted; the model reads a refusal as
        "not granted" and calls request_directory again — same path, same round — parking an
        endless run of consent cards. Answering from the roots list is free when the grant is
        real and breaks the loop when some other consumer is wrong. Returns None whenever a
        real prompt is still owed: no path named, unknown folder, write asked on a read-only
        root, or a primary-promotion request (a different grant, always the user's call).
        """
        if bool(args.get("primary", False)):
            return None
        raw = str(args.get("path", "") or "").strip()
        if not raw:
            return None
        try:
            target = Path(raw).expanduser().resolve()
            if not target.is_dir():
                return None
        except (OSError, ValueError):
            return None
        want_write = bool(args.get("writable", False))
        # `self.roots` only — the session's shared list, attached by build_engine. NOT
        # permissions.roots, which synthesizes a single writable root from workspace_root
        # when it was given none; answering from that would speak for a session whose
        # roots were never wired.
        for r in getattr(self, "roots", None) or []:
            if isinstance(r, dict):
                rp, writable = r.get("path", ""), bool(r.get("writable", False))
            elif isinstance(r, (str, Path)):
                rp, writable = r, False
            else:  # duck-typed RootDir-like
                rp, writable = getattr(r, "path", ""), bool(getattr(r, "writable", False))
            if not rp or (want_write and not writable):
                continue
            try:
                target.relative_to(Path(str(rp)).expanduser().resolve())
            except (ValueError, OSError):
                continue
            return {
                "granted": True,
                "path": str(target),
                "writable": writable,
                "note": (
                    "You already have this folder — it is in the directories listed in "
                    "<system-context>. Nothing was asked of the user. Use it directly by "
                    "absolute path; if a tool still refuses, that is the tool's problem, "
                    "not a missing grant, so report it instead of asking again."
                ),
            }
        return None

    async def _handle_directory_request(
        self, tool_call: ToolCall
    ) -> AsyncIterator[Event]:
        """Emit the grant prompt, await the user's out-of-band decision (which the requester also
        applies to this session's roots), and return the outcome as the tool result."""
        args = tool_call.arguments or {}
        already = self._already_granted(args)
        if already is not None:
            # Never park a consent card for a folder the session already has.
            result: dict[str, Any] = already
        elif self.directory_requester is None:
            result = {
                "granted": False,
                "error": "directory requests aren't available here",
            }
        else:
            yield Event(
                EventType.DIRECTORY_REQUESTED,
                {
                    "reason": str(args.get("reason", "")),
                    "path": str(args.get("path", "")),
                    "writable": bool(args.get("writable", False)),
                    # Root promotion (workspace-scratch-design.md §5): the agent asks for
                    # the folder to become the session's primary workspace — the consent
                    # card must say so, it's a different grant than a plain extra root.
                    "primary": bool(args.get("primary", False)),
                },
            )
            self._audit(
                tool_call,
                stage="directory_requested",
                reason=str(args.get("reason", "")),
            )
            result = await self._interruptible(
                self.directory_requester(dict(args), tool_call.id),
                interrupted={"granted": False, "error": "interrupted by user"},
            ) or {
                "granted": False,
                "error": "no response",
            }

        status = "ok" if result.get("granted") else "denied"
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    async def _handle_ask_user(self, tool_call: ToolCall) -> AsyncIterator[Event]:
        """Emit the question, await the user's out-of-band answer (inline in the live session or
        from the Inbox when unattended), and return it as the tool result."""
        args = tool_call.arguments or {}
        question = str(args.get("question", "")).strip()
        # Grouped form (OPE-51): `questions` alone is a valid call — the singular field may be
        # empty. The asker normalizes/validates the entries; here only "is anything asked?".
        if not question:
            for entry in args.get("questions") or []:
                if isinstance(entry, dict) and str(entry.get("question", "")).strip():
                    question = str(entry["question"]).strip()
                    break
        if self.question_asker is None or not question:
            result: dict[str, Any] = {
                "answer": "",
                "error": (
                    "no question was asked"
                    if not question
                    else "asking isn't available here"
                ),
            }
        else:
            # The asker is mode-aware (attended → live inline prompt; unattended → Inbox), so it
            # owns surfacing the question. The engine just awaits the answer.
            self._audit(tool_call, stage="question_requested", reason=question)
            result = await self._interruptible(
                self.question_asker(dict(args), tool_call.id),
                interrupted={"answer": "", "error": "interrupted by user"},
            ) or {
                "answer": "",
                "error": "no response",
            }

        status = "ok" if (result.get("answer") or result.get("answers")) else "denied"
        if status == "ok":
            self._note_ask_replies(result, question)
        self.messages.append(_tool_result_message(tool_call, result))
        self._audit(
            tool_call,
            stage="finished",
            status=status,
            result=result,
            result_preview=_preview(result),
        )
        yield Event(
            EventType.TOOL_FINISHED,
            {
                "name": tool_call.name,
                "status": status,
                "result_preview": _preview(result),
            },
        )

    def _note_ask_replies(
        self, result: dict[str, Any], question: str = ""
    ) -> None:
        """Record the user's ask_user answer(s) for the reviewer's history (§8.2),
        together with the agent's question — shown to the judge explicitly framed as
        agent-authored data (same Rule-3 discipline as tool arguments), so a structured
        answer counts as evidence for exactly the question's scope (owner ruling
        2026-08-24). Anchored to the number of user messages present now, so the merge
        stays chronological however the session continues.

        A fresh answer also resets the §8.4 denial streak: the user is present and just
        gave direction — the reviewer deserves a fresh look at what follows."""
        self._reviewer_denials = 0
        anchor = sum(1 for m in self.messages if m.get("role") == "user")
        answers = result.get("answers")
        values = (
            [str(v) for v in answers.values()]
            if isinstance(answers, dict)
            else [str(result.get("answer") or "")]
        )
        q = (question or "").strip()
        for text in values:
            text = text.strip()
            if text:
                self._ask_replies.append((anchor, text, q))

    def _inject_steering(self) -> None:
        for text, source in self._steering:
            message: dict[str, Any] = {
                "role": "user",
                "content": text,
                "ts": time.time(),
            }
            if source is not None:
                message["source"] = source
            self.messages.append(message)
        self._steering = []

    def _outbound_messages(self) -> list[dict[str, Any]]:
        """`self.messages` prepared for the provider. The SOLE provider feed (see `_astream`).

        Every message is stripped of the display-only sidecars — `source`, `_display`, and
        `ts` — (providers reject unknown keys), unconditionally — whether or not a
        `<system-context>` block is added. When a context provider yields a non-empty
        string, an ephemeral `<system-context>` block is appended as its own trailing
        `{"role": "user"}` message — an INDEPENDENT message, not glued onto the last real
        user message. Gluing it on used to change that message's bytes every turn (the
        block rides only the newest user message), which invalidated every provider-side
        prompt cache of the conversation prefix on every single turn; as a separate tail
        message, the persisted history stays byte-stable turn over turn and providers can
        place their cache breakpoint before the tail (anthropic keys off
        `SYSTEM_CONTEXT_OPEN` to find it). Never mutates `self.messages`, so neither the
        strip nor the tail message is persisted/replayed.
        """
        # Strip the display-only sidecars — `source` (connector cards), `_display`
        # (e.g. filter-hidden counts), `ts` (append-time timestamps), `t0` (when the tool
        # actually started running), `reasoning` (thinking text), `usage` (token counts)
        # and `finish_reason`/`truncated`/`aborted` (how the round-trip ended) — copying
        # only messages that carry one. Whole `notice` messages (error/interrupted/
        # model-switch markers) are display-only too, and so is an `aborted` assistant
        # message (the thinking from a turn that delivered nothing, kept for the
        # transcript alone): both are dropped entirely rather than stripped, because an
        # empty assistant turn re-sent every round is precisely what it must never become.
        _SIDECARS = (
            "source",
            "_display",
            "ts",
            "t0",
            "reasoning",
            "usage",
            "finish_reason",
            "truncated",
            "aborted",
        )
        # Auto-compaction (OPE-27): everything before the boundary is represented by the
        # compacted block. Outbound-only — the canonical history stays intact — and the
        # block+tail are byte-stable between turns, so prompt caching keeps working.
        source_messages = _compaction.apply_to_outbound(
            self.messages, self.compaction_state
        )
        out = [
            (
                {k: v for k, v in msg.items() if k not in _SIDECARS}
                if any(s in msg for s in _SIDECARS)
                else msg
            )
            for msg in source_messages
            if msg.get("role") != "notice" and not msg.get("aborted")
        ]
        # Crash/interrupt repair (replay-side only): an assistant tool_call whose
        # result never landed — the process died or the turn was interrupted between
        # persisting the assistant message and its tool outputs — makes strict
        # providers reject the whole conversation ("No tool output found for function
        # call …"), bricking the durable session. Synthesize a stub result for each
        # dangling id, appended after the round's real tool replies; the canonical
        # history stays untouched, and when nothing dangles the list is identical.
        repaired: list[dict[str, Any]] = []
        i = 0
        while i < len(out):
            msg = out[i]
            repaired.append(msg)
            i += 1
            if msg.get("role") != "assistant":
                continue
            call_ids = _calls_awaiting_output(msg)
            if not call_ids:
                continue
            answered: set[str] = set()
            while i < len(out) and out[i].get("role") == "tool":
                answered.add(str(out[i].get("tool_call_id") or ""))
                repaired.append(out[i])
                i += 1
            for call_id in call_ids:
                if call_id not in answered:
                    repaired.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": "[tool execution was interrupted before returning a result]",
                        }
                    )
        out = repaired
        # PDF attachments (stored as `file` parts) are adapted to the ACTIVE model right
        # here — never in the persisted history — so a mid-session model switch always
        # re-decides: native PDF models get the real document, the rest get the local
        # text-extract/page-image fallback (pdf_support.py).
        if any(
            isinstance(p, dict) and p.get("type") == "file"
            for msg in out
            if isinstance(msg.get("content"), list)
            for p in msg["content"]
        ):
            caps = self.provider.capabilities(self.model)
            if not getattr(caps, "pdf", False):
                from . import pdf_support

                out = [
                    (
                        {
                            **msg,
                            "content": pdf_support.adapt_content(msg["content"], caps),
                        }
                        if isinstance(msg.get("content"), list)
                        else msg
                    )
                    for msg in out
                ]

        # Images get the same per-turn treatment: a model without vision receives a visible
        # placeholder instead of a payload it would reject. Like the PDF path, this re-decides
        # per call, so a mid-session switch to/from a vision model always does the right thing.
        if any(
            isinstance(p, dict) and p.get("type") == "image_url"
            for msg in out
            if isinstance(msg.get("content"), list)
            for p in msg["content"]
        ):
            caps = self.provider.capabilities(self.model)
            if not getattr(caps, "vision", False):
                placeholder = {
                    "type": "text",
                    "text": "[image attachment — not viewable by this model]",
                }
                out = [
                    (
                        {
                            **msg,
                            "content": [
                                (
                                    placeholder
                                    if isinstance(p, dict)
                                    and p.get("type") == "image_url"
                                    else p
                                )
                                for p in msg["content"]
                            ],
                        }
                        if isinstance(msg.get("content"), list)
                        else msg
                    )
                    for msg in out
                ]

        # Repeated identical reads: keep only the newest copy. Runs here — on the
        # post-compaction view, before the `<system-context>` tail is added — so it
        # dedupes exactly the verbatim history the provider is about to see. Outbound-only
        # like everything above. `_supersede_repeated_reads` says how this sits against
        # `_clip_tool_result` and compaction.
        out = _supersede_repeated_reads(out)

        context = (
            self.context_provider() if self.context_provider is not None else ""
        ) or ""
        if not context:
            return out
        block = f"{SYSTEM_CONTEXT_OPEN}\n{context}\n</system-context>"
        out.append({"role": "user", "content": block})
        return out


# Read-only tools whose answer is fully determined by their arguments: called twice with
# byte-identical arguments, the second call can only be a newer copy of the first. `run_shell`
# is deliberately absent — two identical commands can straddle a change the model is comparing
# across, and the older output is the half of that comparison. (`list_files` is aisuite's
# files toolkit; the other three are ours — see catalog.py.)
_IDEMPOTENT_READS = frozenset({"read_file", "grep", "list_files", "git_log"})
_SUPERSEDED_NOTE = (
    "[superseded — this exact read was repeated later in the conversation; "
    "see the newer result]"
)
# Collapsing rewrites history mid-thread, which costs one cache miss to buy a permanently
# smaller context. Only worth it when the copy being dropped is actually large. Must stay
# BELOW `_TOOL_RESULT_MAX_CHARS`: every result in history was already clipped to that cap
# on the way in, so a floor at or above it would mean nothing ever qualifies.
_SUPERSEDE_MIN_CHARS = 2_000


def _supersede_repeated_reads(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only the newest result of each repeated identical read.

    Reading the same file three times leaves three full copies in the transcript, and every
    later round-trip pays for all three. Compaction already rules that a stale memory of a
    file is worse than no memory (`compaction.py`) — but it only fires at the window
    threshold, so a turn can run a hundred calls before it applies. This applies the same
    rule every turn. Outbound-only: the canonical history keeps every copy.

    Where it sits against the other two bounds on what a tool result costs:

    - `_clip_tool_result` runs at APPEND time, so every result seen here is already at most
      `_TOOL_RESULT_MAX_CHARS`. The two are orthogonal — the clip bounds what ONE result may
      cost, this bounds how many times the SAME result is paid for — and the order is fixed
      by where each lives: clip first (into history), supersede later (out of it). A read
      clipped at the cap is the typical customer: four reads of one big file leave four
      8,000-char copies in history, and this sends one.
    - Compaction (`_compaction.apply_to_outbound`) has already replaced everything before
      its boundary with the summary block by the time this runs, so only the verbatim tail
      is scanned; a read whose twin was summarized away has no older copy to supersede.

    The newest copy wins even when it is an error or the crash-repair stub: the model then
    sees the note, sees the error, and re-reads — one extra read, never a silently stale file.
    """
    calls: dict[str, tuple[str, str]] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in _IDEMPOTENT_READS and tc.get("id"):
                calls[tc["id"]] = (fn["name"], fn.get("arguments") or "")
    if not calls:
        return messages
    newest: dict[tuple[str, str], str] = {}
    sizes: dict[str, int] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        call_id = msg.get("tool_call_id")
        key = calls.get(call_id)
        if key is None or not isinstance(msg.get("content"), str):
            continue
        newest[key] = call_id
        sizes[call_id] = len(msg["content"])
    stale = {
        call_id
        for call_id, key in calls.items()
        if newest.get(key) not in (None, call_id)
        and sizes.get(call_id, 0) >= _SUPERSEDE_MIN_CHARS
    }
    if not stale:
        return messages
    return [
        (
            {**msg, "content": _SUPERSEDED_NOTE}
            if msg.get("role") == "tool" and msg.get("tool_call_id") in stale
            else msg
        )
        for msg in messages
    ]


def _calls_awaiting_output(message: dict[str, Any]) -> list[str]:
    """Every call id on one assistant message that a strict provider will demand a result for,
    in call order and deduped.

    Canonical `tool_calls` is the usual source, but it is not the only one: a provider-private
    sidecar (`_openai`) is replayed to that provider VERBATIM, so a `function_call` item living
    only there is sent unanswered and 400s the whole conversation ("No tool output found for
    function call …") even though the canonical fields look clean. Reading both keeps the repair
    honest about what actually goes on the wire.
    """
    ids = [str((call or {}).get("id") or "") for call in message.get("tool_calls") or []]
    for key, sidecar in message.items():
        if not key.startswith("_") or not isinstance(sidecar, dict):
            continue
        for item in sidecar.get("items") or []:
            if isinstance(item, dict) and item.get("type") == "function_call":
                ids.append(str(item.get("call_id") or ""))
    return list(dict.fromkeys(i for i in ids if i))


def _models_that_report_finish(
    messages: list[dict[str, Any]], default_model: str
) -> set[str]:
    """Which models this conversation has already been seen reporting a finish reason —
    `TurnEngine._finish_reason_seen`, recovered from the record.

    Without this the gate would be re-learned from scratch on every restart, engine
    eviction and session resume, and the first genuinely severed stream after each of
    those would be filed as "the model returned an empty response" — wrong on the facts,
    and worth only the one courtesy retry an empty answer gets.

    The model id rides the `usage` sidecar, tagged there so per-model rollups survive a
    mid-session switch, and a message carrying one is attributed to that model wherever it
    sits. A message WITHOUT one is the awkward case, and it is not rare: `usage` is only
    written when the backend reported any, and "reports a finish reason but no usage" is
    exactly the shape of the compat endpoints this gate exists for. Such a message can
    only be credited to the current model when nothing has switched since — so attribution
    stops at the last `model_switch` marker, and anything untagged before it is skipped
    rather than guessed. Guessing there is the one mistake that matters: it would vouch
    for a model that has never been watched, which is precisely what the gate is for."""
    seen: set[str] = set()
    history = messages or []
    # Everything after the last switch was produced by the model in play now; before it,
    # by something we can't name without a tag.
    current_segment = 1 + max(
        (
            i
            for i, m in enumerate(history)
            if m.get("role") == "notice" and m.get("kind") == "model_switch"
        ),
        default=-1,
    )
    for index, message in enumerate(history):
        if message.get("role") != "assistant" or not message.get("finish_reason"):
            continue
        usage = message.get("usage")
        model = (usage or {}).get("model") if isinstance(usage, dict) else None
        if model:
            seen.add(str(model))
        elif index >= current_segment:
            seen.add(default_model)
    return seen


def _assistant_message(
    turn: AssistantTurn, model: Optional[str] = None, *, aborted: bool = False
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": turn.text or "",
        "ts": time.time(),
    }
    if aborted:
        # This turn delivered nothing — it is kept ONLY to show the user the thinking they
        # watched before the stream died. `_outbound_messages` drops the whole message, so
        # no provider ever sees a blank assistant turn (and no model learns to imitate it).
        message["aborted"] = True
    if turn.usage is not None:
        # Display/aggregation sidecar (like `reasoning`): persisted with the message,
        # stripped before provider calls. Tagged with the model that produced it so
        # per-model rollups survive mid-session model switches.
        message["usage"] = {"model": model, **turn.usage.as_dict()}
    if turn.reasoning:
        # Display-only thinking text — rendered by the GUI, stripped for every provider
        # (`_outbound_messages`); provider-private replay blocks go via `extras` instead.
        message["reasoning"] = turn.reasoning
    if turn.finish_reason:
        # How the round-trip ended, kept so a stored transcript can be told apart after
        # the fact: a severed stream (no finish reason at all) vs. the output-token limit
        # vs. a model that really did answer with nothing. Dropping it is what made the
        # 2026-09-18 report unexplainable from the record alone. Display/diagnostic
        # sidecar like `usage` — stripped before every provider call.
        message["finish_reason"] = turn.finish_reason
    if turn.truncated:
        # Only set when the provider can tell a cut stream from a clean one, and only
        # when it was cut (providers/base.py) — so its absence means "clean", never
        # "unknown from a backend that doesn't say".
        message["truncated"] = True
    if turn.extras:
        # Provider-private sidecars (e.g. `_gemini` thought signatures) persist with the
        # message; the owning provider reattaches them, the rest strip them (base.py).
        message.update(turn.extras)
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in turn.tool_calls
        ]
    return message


_MANGLED_PREVIEW_CHARS = 200


def _is_mangled(tool_call: ToolCall) -> bool:
    """Provider arg-parsers fall back to `{"_raw": <unparsed text>}` when a tool call's
    arguments aren't a JSON object (typically a stream truncated mid-arguments)."""
    return set(tool_call.arguments or {}) == {"_raw"}


def _sanitize_mangled_calls(turn: AssistantTurn) -> None:
    """Shrink each mangled call's stored raw text to a short preview BEFORE the turn
    enters history. The full text is junk (half a JSON document): replaying it costs
    thousands of tokens per turn and, worse, teaches the model that `_raw` is a real
    parameter shape it should imitate."""
    for tc in turn.tool_calls:
        if _is_mangled(tc):
            raw = str(tc.arguments.get("_raw") or "")
            if len(raw) > _MANGLED_PREVIEW_CHARS:
                tc.arguments = {
                    "_raw": raw[:_MANGLED_PREVIEW_CHARS]
                    + f"… [unparsed tool-call text, {len(raw)} chars, truncated in history]"
                }


# The one place a bound can be put on what a tool result costs FOREVER. A tool result is
# appended to history and then re-sent on every subsequent round trip of the session, so
# its size is paid once per remaining turn, not once. Until this cap existed the engine
# enforced nothing and the ceiling was whatever each tool happened to choose — `run_shell`
# alone allows 20,000 chars (~5,000 tokens), i.e. a SINGLE call could plant more in the
# history than the entire system prompt and tool catalogue combined.
#
# 8,000 chars is deliberately generous: it clears a long file read or a full test run, so
# the cap only bites on genuinely runaway output (a `find /`, a minified bundle, a 50k-line
# log). The trailing marker is written FOR THE MODEL — it says how much was dropped and
# what to do about it, because a silent truncation reads as "that's all there was" and
# sends the model off reasoning about a file it only half saw.
_TOOL_RESULT_MAX_CHARS = 8_000
_TOOL_RESULT_HEAD_SHARE = 0.7  # keep mostly the head; the tail usually holds the summary


def _clip_tool_result(content: str) -> str:
    """Bound one tool result before it enters history. Keeps a head and a tail — the head
    because output is usually front-loaded, the tail because exit codes, totals and error
    summaries live at the end and dropping them is what makes a truncation misleading."""
    if len(content) <= _TOOL_RESULT_MAX_CHARS:
        return content
    budget = _TOOL_RESULT_MAX_CHARS
    head = int(budget * _TOOL_RESULT_HEAD_SHARE)
    tail = budget - head
    dropped = len(content) - budget
    return (
        content[:head]
        + f"\n\n… [{dropped} chars omitted from the middle of this result to keep the "
        "conversation affordable — it is NOT the whole output. Re-run narrowed (a filter, "
        "a line range, a smaller path) if you need what was dropped.]\n\n"
        + content[-tail:]
    )


def _tool_result_message(tool_call: ToolCall, result: Any) -> dict[str, Any]:
    content = result if isinstance(result, str) else json.dumps(result, default=str)
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": _clip_tool_result(content),
        "ts": time.time(),
    }


def _tool_error_message(tool_call: ToolCall, reason: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps({"error": "tool call not executed", "reason": reason}),
        "ts": time.time(),
    }


def _preview(value: Any, max_chars: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.replace("\n", "\\n")
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
