"""Interactive prompts over messaging — buttons instead of free-text replies.

When an Inbox item is mirrored to a channel, discrete choices (approve/deny, an ask_user option)
render as **buttons**. The item id rides in each button's value, so a click resolves the exact
item — no `[ow:id]`-in-reply fragility, no thread tracking. Free-text answers aren't offered over
messaging (the user opens the app for those).

Provider-agnostic: a `Button` is `(label, value)`; each adapter renders it natively (Slack Block
Kit, Telegram inline keyboard, …). The value is opaque to the adapter — `encode`/`decode` here own
its meaning: `(item_id, resolution)`.

Personal WeChat has no buttons at all, so its mirror is a **numbered plain-text card**:
`choices_for` is the one place that knows what each kind's choices and resolutions are, and both
renderings — Slack buttons and the WeChat card — are derived from it. The Chinese copy every
WeChat message uses lives here as module constants (same precedent as the DM session title in
`manager.py`), so the wording sits in one place rather than smeared across the manager.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .inbox import (
    KIND_APPROVAL,
    KIND_DIRECTORY,
    KIND_PLAN,
    KIND_QUESTION,
    KIND_TOOL,
)
from .tools.ask import option_label


@dataclass
class Button:
    label: str
    value: str  # opaque to the adapter; encode()/decode() own its meaning


@dataclass
class Choice:
    """One discrete answer to an Inbox prompt.

    `label` is the adapter-facing English text (Slack buttons keep rendering exactly what they
    always did). `resolution` is what actually lands in `InboxStore.resolve` — for directory /
    plan / tool prompts that is a JSON string, because their consumers parse it back
    (`_parse_inbox_json` in the manager, `_parse_json` in the WS handler). `intent`
    ("allow"/"deny", or None for an ask_user option) is what lets a keyword reply — "approve",
    "同意" — map onto the right choice without re-deriving that per surface.
    """

    label: str
    resolution: str
    intent: Optional[str] = None


# -- WeChat copy (one place; the manager imports these) --------------------------
WX_CARD_PREFIX = "【需要你确认】"
WX_KIND_TITLES = {
    KIND_APPROVAL: "需要批准一次工具调用",
    KIND_QUESTION: "需要你回答一个问题",
    KIND_DIRECTORY: "需要授权访问一个文件夹",
    KIND_PLAN: "需要确认一份计划",
    KIND_TOOL: "需要确认安装一个工具",
}
WX_LABEL_ALLOW = "同意"
WX_LABEL_DENY = "拒绝"
WX_PATH_HINT = "也可直接回复一个绝对路径"
WX_NO_PATH_HINT = "请直接回复要授权的绝对路径"
WX_SUGGESTED_PATH = "建议路径：{path}（{access}）"
WX_WRITABLE = "可写"
WX_READONLY = "只读"
WX_TTL_NOTE = "{minutes} 分钟内有效"
WX_OPEN_APP = "请在电脑端回答"
WX_FREE_TEXT_HINT = "请直接回复你的答案"
WX_ALREADY_DONE = "该请求已处理或已过期。"
WX_NUDGE = "我还在等你确认：回复 1 同意 / 2 拒绝。"
WX_BAD_PATH = "这不是一个有效的绝对目录路径。请重新回复完整路径，或回复 1 同意 / 2 拒绝。"
WX_TIMED_OUT = "已超时，按拒绝处理。"
WX_ACK = "已收到：{outcome}"
WX_RESOLVED_ELSEWHERE = "已在电脑端处理：{outcome}"


def encode(item_id: str, resolution: str) -> str:
    return json.dumps({"id": item_id, "r": resolution})


def decode(value: str) -> Optional[tuple[str, str]]:
    """`(item_id, resolution)` from a button value, or None if it isn't ours."""
    try:
        d = json.loads(value)
        if isinstance(d, dict) and d.get("id"):
            return str(d["id"]), str(d.get("r", ""))
    except Exception:
        pass
    return None


def _grouped(item) -> bool:
    """A multi-question ask_user form — no single answer can resolve it over messaging."""
    return len(getattr(item, "questions", None) or []) > 1


def choices_for(item) -> list[Choice]:
    """Every discrete answer an Inbox item offers, in display order.

    The resolution strings are the shapes the CONSUMERS parse, not the card's wording:
      * approval — "allow" / "deny" (`SessionManager.approval_outcome`)
      * question — the chosen option's label (what the agent receives verbatim)
      * directory — `{"granted": …, "path": …, "writable": …}` (`inbox_directory_requester`
        and the WS `directory_requester`)
      * plan — `{"approved": true, "mode": "interactive"}` / `{"approved": false}`
      * tool — `{"approved": …}` (the WS `tool_requester`)
    Returns [] when nothing discrete can be offered (notification, grouped form, free-text-only
    question) — the caller then falls back to plain text plus an "open the app" hint.
    """
    kind = getattr(item, "kind", "")
    if kind == KIND_APPROVAL:
        return [
            Choice("Approve", "allow", "allow"),
            Choice("Deny", "deny", "deny"),
        ]
    if kind == KIND_QUESTION:
        # Grouped questions (OPE-51): one choice row can't answer 2+ questions. A ONE-item
        # group falls through — `question_item_fields` already surfaced that question's
        # options as item.options.
        if _grouped(item):
            return []
        return [
            Choice(option_label(opt), option_label(opt))
            for opt in (getattr(item, "options", None) or [])
        ]
    if kind == KIND_DIRECTORY:
        data = getattr(item, "data", None) or {}
        path = str(data.get("path", "") or "").strip()
        writable = bool(data.get("writable", False))
        out: list[Choice] = []
        if path:
            # Accepting the agent's own proposal is the only grant a phone can express —
            # there is no folder picker on the other end. With no proposed path, the card
            # asks for one instead of offering a grant that would resolve to nothing.
            out.append(
                Choice(
                    "Grant",
                    json.dumps(
                        {"granted": True, "path": path, "writable": writable},
                        ensure_ascii=False,
                    ),
                    "allow",
                )
            )
        out.append(Choice("Decline", json.dumps({"granted": False}), "deny"))
        return out
    if kind == KIND_PLAN:
        return [
            Choice(
                "Approve",
                json.dumps({"approved": True, "mode": "interactive"}),
                "allow",
            ),
            Choice("Reject", json.dumps({"approved": False}), "deny"),
        ]
    if kind == KIND_TOOL:
        return [
            Choice("Install", json.dumps({"approved": True}), "allow"),
            Choice("Skip", json.dumps({"approved": False}), "deny"),
        ]
    return []


def deny_resolution(item) -> str:
    """The resolution that declines this item — what an expired prompt falls back to."""
    for choice in choices_for(item):
        if choice.intent == "deny":
            return choice.resolution
    return "deny"


def _structured_intent(resolution: str) -> Optional[str]:
    """allow/deny read out of a JSON resolution's own verdict field, or None.

    The resolutions that actually land are NOT limited to the canonical ones `choices_for`
    offers: a WeChat reply can type its own folder path (`{"granted": true, "path": <what the
    user typed>, …}`), and the app's "Approve and run" sends `mode: "bypass-approvals"` where
    the card offers `"interactive"`. Both would fail a string compare — and a receipt would
    then read "已收到：{"granted": true, …}". The boolean each consumer itself reads is what
    decides instead."""
    try:
        parsed = json.loads(resolution)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    for field in ("granted", "approved"):
        if field in parsed:
            return "allow" if parsed[field] else "deny"
    return None


def outcome_text(item, resolution: str) -> str:
    """One-word Chinese summary of a resolution, for a WeChat receipt."""
    for choice in choices_for(item):
        if choice.resolution == resolution:
            if choice.intent == "allow":
                return WX_LABEL_ALLOW
            if choice.intent == "deny":
                return WX_LABEL_DENY
            # An ask_user option answers with its own words; that IS the outcome.
            return choice.label
    intent = _structured_intent(resolution)
    if intent == "allow":
        return WX_LABEL_ALLOW
    if intent == "deny":
        return WX_LABEL_DENY
    return resolution or WX_LABEL_DENY


def buttons_for(item) -> list[Button]:
    """The discrete-choice buttons for an Inbox item, or [] if it has none (free-text question,
    notification, …) — the caller then sends plain text with an "open the app" hint.

    Slack/Telegram render buttons for the two kinds they always have: an approval and a
    single-select ask_user. Directory / plan / tool prompts carry structured resolutions with
    no button surface of their own, so they keep their plain-text mirror (the numbered WeChat
    card is what answers those)."""
    if item.kind not in (KIND_APPROVAL, KIND_QUESTION):
        return []
    return [Button(c.label, encode(item.id, c.resolution)) for c in choices_for(item)]


def weixin_prompt(item, minutes: int) -> str:
    """The plain-text WeChat card for a pending prompt.

    No buttons exist on personal WeChat, so the choices are NUMBERED and the reply is a digit
    (`inbox_routing.choice_from_reply` reads it back). The `[ow:<id>]` token rides along so a
    quoted reply still correlates.
    """
    lines: list[str] = [
        WX_CARD_PREFIX + WX_KIND_TITLES.get(item.kind, WX_KIND_TITLES[KIND_APPROVAL])
    ]
    title = (getattr(item, "title", "") or "").strip()
    if title:
        lines.append(title)
    body = (getattr(item, "body", "") or "").strip()
    if body:
        lines.append(body)
    data = getattr(item, "data", None) or {}
    proposed = str(data.get("path", "") or "").strip()
    if item.kind == KIND_DIRECTORY and proposed:
        access = WX_WRITABLE if data.get("writable") else WX_READONLY
        lines.append(WX_SUGGESTED_PATH.format(path=proposed, access=access))
    if _grouped(item):
        lines.append(WX_OPEN_APP)
    else:
        choices = choices_for(item)
        for n, choice in enumerate(choices, 1):
            label = {"allow": WX_LABEL_ALLOW, "deny": WX_LABEL_DENY}.get(
                choice.intent or "", choice.label
            )
            lines.append(f"{n} {label}")
        if item.kind == KIND_DIRECTORY:
            lines.append(WX_PATH_HINT if proposed else WX_NO_PATH_HINT)
        elif not choices:
            lines.append(
                WX_FREE_TEXT_HINT if getattr(item, "allow_text", True) else WX_OPEN_APP
            )
    lines.append(WX_TTL_NOTE.format(minutes=minutes))
    lines.append(f"[ow:{item.id}]")
    return "\n".join(lines)


def choice_payloads(choices: list[Choice]) -> list[dict[str, Any]]:
    """Persistable form of the choices — they ride in `item.data["wx"]` so a reply can be
    scored against exactly what the user was shown, even after a restart."""
    return [
        {"label": c.label, "resolution": c.resolution, "intent": c.intent}
        for c in choices
    ]
