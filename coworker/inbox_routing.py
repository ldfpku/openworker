"""Multi-inbox routing — named inboxes + delivery bindings.

An inbox is a named queue with optional delivery binding(s): in-app is always the store of
record; a binding can also mirror items to a Slack channel or Telegram chat. Sessions route to
an inbox by a per-session override, else the persona's default, else ``"default"``. Bindings
are bidirectional: an item is delivered to the bound channel with its id embedded, and an
inbound reply (correlated by that id) resolves the item — so the connectors/mobile are just
transports of the same items. The gateway wiring is injected (a ``sender`` callable) so this
module stays testable without touching Slack/Telegram.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

DEFAULT_INBOX = "default"
# Embeds the item id in a delivered message. Emitted as [ow:…] since the bot's rebrand
# to OpenWorker (2026-07-22); the legacy [ocw:…] spelling stays parseable so replies to
# messages sent before the rename still resolve.
_ID_TOKEN = re.compile(r"\[o(?:c)?w:([0-9a-f]{6,})\]")


@dataclass
class InboxBinding:
    name: str
    channel: Optional[str] = None  # None (in-app only) | "slack" | "telegram"
    target: str = ""  # channel id / chat id for the binding


class InboxRouting:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._bindings: dict[str, InboxBinding] = {
            DEFAULT_INBOX: InboxBinding(DEFAULT_INBOX)
        }
        self._persona_default: dict[str, str] = {}
        self._session_override: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path and self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in data.get("bindings", []):
                b = InboxBinding(**raw)
                self._bindings[b.name] = b
            self._persona_default = dict(data.get("persona_default", {}))
            self._session_override = dict(data.get("session_override", {}))

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "bindings": [asdict(b) for b in self._bindings.values()],
                    "persona_default": self._persona_default,
                    "session_override": self._session_override,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- config -----------------------------------------------------------------
    def set_binding(
        self, name: str, *, channel: Optional[str] = None, target: str = ""
    ) -> None:
        with self._lock:
            self._bindings[name] = InboxBinding(name, channel, target)
            self._save()

    def binding_for(self, name: str) -> InboxBinding:
        return self._bindings.get(name) or InboxBinding(name)

    def set_persona_default(self, persona_id: str, inbox_name: str) -> None:
        with self._lock:
            self._persona_default[persona_id] = inbox_name
            self._save()

    def set_session_override(self, session_id: str, inbox_name: str) -> None:
        with self._lock:
            self._session_override[session_id] = inbox_name
            self._save()

    # -- resolution -------------------------------------------------------------
    def route_for(self, session_id: str, persona_id: Optional[str] = None) -> str:
        """Per-session override > persona default > the global default inbox."""
        if session_id in self._session_override:
            return self._session_override[session_id]
        if persona_id and persona_id in self._persona_default:
            return self._persona_default[persona_id]
        return DEFAULT_INBOX

    def bindings(self) -> list[dict]:
        return [asdict(b) for b in self._bindings.values()]


# -- delivery + inbound correlation ---------------------------------------------
Sender = Callable[[str, str, str], None]  # (channel, target, text) -> None


def deliver(item, binding: InboxBinding, sender: Optional[Sender]) -> bool:
    """Mirror an inbox item to its bound channel (if any). The item id is embedded so an inbound
    reply can be correlated back. In-app-only bindings deliver nothing here. Returns True if a
    channel message was sent."""
    if not binding.channel or sender is None:
        return False
    text = f"{item.title}\n{item.body}\n[ow:{item.id}]".strip()
    sender(binding.channel, binding.target, text)
    return True


# Decision keywords for a channel reply. Matched against the reply's LEADING word/emoji
# only (see _reply_intent). Substring matching turned "disallow" into allow and "note"
# into deny; whole-word matching anywhere (the interim fix) still inverted negated
# replies — "I cannot approve this yet" matched \bapprove\b and, with allow checked
# first, executed the declined action. Leading-word intent keeps "Yes, go ahead" /
# "No." / "👍" working; everything else is a free-text answer, which the approval path
# already maps to deny — the safe default for an approval gate.
#
# The Chinese entries carry the same leading-word semantics: a WeChat reply arrives as a bare
# word ("同意", "拒绝。") with no spaces, so the whole message IS the leading token.
_ALLOW_WORDS = frozenset(
    {
        "approve",
        "approved",
        "allow",
        "allowed",
        "yes",
        "同意",
        "允许",
        "批准",
        "好",
        "好的",
        "可以",
    }
)
_DENY_WORDS = frozenset(
    {"deny", "denied", "reject", "rejected", "no", "拒绝", "不行", "取消", "否"}
)
_ALLOW_EMOJI = ("👍", "✅")
_DENY_EMOJI = ("👎", "❌")
# CJK punctuation included: "同意。" and "拒绝！" have to trim to the bare word the way
# their ASCII counterparts already do.
_TOKEN_TRIM = ".,!?:;'\"()" + "。，！？：；、“”‘’（）"


def _reply_intent(text: str) -> Optional[str]:
    """Allow/deny intent from the first word (or emoji) of a reply, else None."""
    first = text.split()[0] if text.split() else ""
    if first.startswith(_ALLOW_EMOJI):  # startswith: tolerate skin-tone modifiers
        return "allow"
    if first.startswith(_DENY_EMOJI):
        return "deny"
    word = first.strip(_TOKEN_TRIM).lower()
    if word in _ALLOW_WORDS:
        return "allow"
    if word in _DENY_WORDS:
        return "deny"
    return None


def resolve_from_reply(
    reply: str, resolve: Callable[[str, str], bool]
) -> Optional[bool]:
    """Correlate an inbound channel reply to its item (by the embedded id) and resolve it.

    Looks for the ``[ow:<id>]`` token (or legacy ``[ocw:…]``) and an allow/deny intent in the
    reply's leading word; falls back to treating the whole message as a free-text answer.
    ``resolve(item_id, resolution)`` is the InboxStore.resolve.
    Returns the resolve() result, or None if no item id was found."""
    m = _ID_TOKEN.search(reply or "")
    if not m:
        return None
    item_id = m.group(1)
    text = _ID_TOKEN.sub("", reply).strip()
    resolution = _reply_intent(text) or text  # free-text answer to a question
    return resolve(item_id, resolution)


# -- numbered replies (the WeChat card) -----------------------------------------
# Personal WeChat has no buttons, so a mirrored prompt is a NUMBERED plain-text card and the
# answer comes back as a digit. Phone keyboards happily produce full-width digits ("１"), and
# people prefix them ("回复 2"), so both are normalized before matching.
_CHOICE_NUMBER = re.compile(r"^(?:回复)?\s*([1-9])[.、,:：)）]?$")


def to_halfwidth(text: str) -> str:
    """Full-width ASCII (and the ideographic space) folded to their half-width forms."""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def is_choice_number(text: str) -> bool:
    """True when a reply is nothing but a choice number — the shape that means "I am
    answering a card", so an expired prompt can say so instead of silently starting a turn."""
    return _CHOICE_NUMBER.match(to_halfwidth(str(text or "")).strip()) is not None


def choice_from_reply(
    text: str, choices: Sequence[Any], allow_text: bool = False
) -> Optional[str]:
    """The resolution a plain-text reply selects, or None when nothing matched.

    Pure: `choices` is any sequence of objects carrying ``label`` / ``resolution`` /
    ``intent`` (``interactions.Choice``, or the dicts-turned-Choices persisted in
    ``item.data["wx"]``). Order of precedence — the card's own numbering, then an
    allow/deny keyword, then an option typed out verbatim, then (only when the prompt
    accepts one) the whole message as a free-text answer.
    """
    norm = to_halfwidth(str(text or "")).strip()
    if not norm:
        return None
    m = _CHOICE_NUMBER.match(norm)
    if m:
        index = int(m.group(1)) - 1
        # A number the card never offered is NOT a free-text answer: "5" against a
        # two-option prompt is a miss, and answering the agent with "5" would be worse
        # than asking again.
        if 0 <= index < len(choices):
            return getattr(choices[index], "resolution", None)
        return None
    intent = _reply_intent(norm)
    if intent is not None:
        for choice in choices:
            if getattr(choice, "intent", None) == intent:
                return getattr(choice, "resolution", None)
    for choice in choices:
        label = str(getattr(choice, "label", "") or "").strip()
        if label and label.lower() == norm.lower():
            return getattr(choice, "resolution", None)
    return norm if allow_text else None
