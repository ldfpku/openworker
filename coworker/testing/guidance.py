"""Shared recognizer for the engine's 开工前核对 diagnosis completion.

`TurnEngine._preflight` (coworker/engine.py) makes one cheap completion on the session's
own `ProviderClient` before the first model call of an attended session's first task
message (coworker/guidance.py). Like the auto-title call (see `autotitle.py`), it rides the
SAME provider a test's scripted turns use, so a scripted double that does not recognize it
would hand its first queued chat turn to the diagnosis and shift every later turn by one.

Every scripted `ProviderClient` double behind an attended WebSocket session needs this
check. The default reply says "not a task", which makes the engine skip the pre-flight
without persisting anything — a no-op for every assertion on transcript or Inbox state.
"""

from __future__ import annotations

import json
from typing import Any

from ..guidance import DIAGNOSIS_MARKER
from ..providers import AssistantTurn


def is_diagnosis_call(messages: list[dict[str, Any]] | None) -> bool:
    """True when `messages` is the pre-flight diagnosis completion (its system prompt
    opens with `DIAGNOSIS_MARKER`), never a scripted chat turn."""
    if not messages:
        return False
    return str(messages[0].get("content", "")).startswith(DIAGNOSIS_MARKER)


def diagnosis_reply(diagnosis: dict[str, Any] | None = None) -> AssistantTurn:
    """The `AssistantTurn` a scripted provider hands back for a diagnosis call. Default:
    `{"is_task": false}` → the engine skips the pre-flight. Pass a dict to script a real
    diagnosis (shape in coworker/guidance.py)."""
    payload = diagnosis if diagnosis is not None else {"is_task": False}
    return AssistantTurn(text=json.dumps(payload, ensure_ascii=False), finish_reason="stop")
