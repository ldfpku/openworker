"""Shared recognizer for the manager's fire-and-forget auto-title completion.

`SessionManager._maybe_autotitle` (coworker/server/manager.py) fires a title-generation
completion on the session's own `ProviderClient` — once from `run_turn` at turn start
(app.py) and again, for sessions still untitled, from `mark_idle` at turn end. It rides
the SAME provider a test's scripted turns use, on a worker thread (`asyncio.to_thread`),
so it can race a chat turn and — unless a scripted provider recognizes and diverts it —
pop a queued turn meant for the chat script, or get counted as a chat call.

Every scripted `ProviderClient` test double in tests/ needs to recognize this call. Before
this module, five of them each hardcoded the same substring test independently (see git
history: tests/test_skills_api.py, tests/test_server.py x2, tests/test_autotitle.py,
tests/test_ui_refresh_e2e.py). This module is the one place that keys off
`SessionManager._AUTOTITLE_PROMPT`, so the recognition logic can't drift out of sync with
the prompt across files. tests/test_autotitle.py asserts `AUTOTITLE_MARKER` is actually a
substring of the live prompt, so a future prompt rewrite that drops the marker fails loudly
there instead of silently breaking every provider double at once.

This module only supplies RECOGNITION. What a test double does once it recognizes a title
call — answer from a dedicated queue, record it separately, split it into its own bucket —
is still each file's own business; see the existing five for the range of styles.
"""

from __future__ import annotations

from typing import Any

from ..providers import AssistantTurn

# `SessionManager._AUTOTITLE_PROMPT` (coworker/server/manager.py) opens with this exact
# sentence. Keep this in sync with that prompt — tests/test_autotitle.py pins the two
# together with an assertion, so a mismatch fails there first.
AUTOTITLE_MARKER = "title chat sessions"


def is_autotitle_call(messages: list[dict[str, Any]] | None) -> bool:
    """True when `messages` (the `ProviderClient.complete` `messages` kwarg) is the
    manager's auto-title completion rather than a scripted chat turn.

    The auto-title call always opens with a system message whose content is
    `SessionManager._AUTOTITLE_PROMPT` (see `_generate_autotitle`); every other call this
    codebase makes to a `ProviderClient` is a real chat/tool turn, never a system message
    carrying that sentence, so checking the first message is enough — same check every
    existing scripted-provider double already made ad hoc.
    """
    if not messages:
        return False
    return AUTOTITLE_MARKER in str(messages[0].get("content", ""))


def autotitle_reply(text: str = "small-talk") -> AssistantTurn:
    """The `AssistantTurn` a scripted provider should hand back for an auto-title call.

    Defaults to the "small-talk" sentinel: `SessionManager._generate_autotitle`
    recognizes that exact reply (case/punctuation-normalized) and returns without calling
    `set_auto_title` or broadcasting a `session_title` event (manager.py) — confirmed by
    reading that method. So the default reply is a no-op as far as any test's assertions
    on session/title state are concerned; pass a different `text` when a test wants to
    assert on the generated title itself (see tests/test_autotitle.py,
    tests/test_server.py's SlowProvider).
    """
    return AssistantTurn(text=text, finish_reason="stop")
