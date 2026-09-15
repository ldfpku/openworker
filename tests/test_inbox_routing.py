"""Phase 3 gate — multi-inbox routing: named bindings, route resolution, delivery + reply."""

from __future__ import annotations

from coworker.inbox import InboxStore
from coworker.inbox_routing import (
    DEFAULT_INBOX,
    InboxRouting,
    choice_from_reply,
    deliver,
    is_choice_number,
    resolve_from_reply,
    to_halfwidth,
)
from coworker.interactions import Choice


def test_route_precedence(tmp_path):
    r = InboxRouting(tmp_path / "routing.json")
    r.set_binding("ops", channel="slack", target="#ops-coworker")
    r.set_persona_default("ops", "ops")
    # Persona default applies...
    assert r.route_for("s1", "ops") == "ops"
    # ...unless a per-session override wins.
    r.set_session_override("s1", DEFAULT_INBOX)
    assert r.route_for("s1", "ops") == DEFAULT_INBOX
    # Unbound persona/session → default.
    assert r.route_for("s2", "cowork") == DEFAULT_INBOX


def test_bindings_persist(tmp_path):
    InboxRouting(tmp_path / "routing.json").set_binding(
        "ops", channel="telegram", target="123"
    )
    r2 = InboxRouting(tmp_path / "routing.json")
    b = r2.binding_for("ops")
    assert b.channel == "telegram" and b.target == "123"


def test_deliver_to_channel_embeds_item_id(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    routing = InboxRouting(tmp_path / "routing.json")
    routing.set_binding("ops", channel="slack", target="#ops")
    item = store.add_approval("s1", "Restart service?", body="prod web-1", inbox="ops")

    sent = {}

    def sender(channel, target, text):
        sent.update(channel=channel, target=target, text=text)

    assert deliver(item, routing.binding_for("ops"), sender) is True
    assert sent["channel"] == "slack" and sent["target"] == "#ops"
    assert f"[ow:{item.id}]" in sent["text"]  # rebrand: emits [ow:…] since 2026-07-22


def test_in_app_only_binding_delivers_nothing(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    routing = InboxRouting(tmp_path / "routing.json")
    item = store.add_approval("s1", "x", inbox=DEFAULT_INBOX)
    calls = []
    assert (
        deliver(item, routing.binding_for(DEFAULT_INBOX), lambda *a: calls.append(a))
        is False
    )
    assert calls == []


def test_inbound_reply_resolves_correct_item(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Deploy?", inbox="ops")
    # Current token spelling…
    ok = resolve_from_reply(f"approve [ow:{item.id}]", store.resolve)
    assert ok is True
    assert store.get(item.id).resolution == "allow"


def test_inbound_freetext_answer_to_question(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    q = store.add_question("s1", "Which region?")
    res = resolve_from_reply(f"us-east-1 [ow:{q.id}]", store.resolve)
    assert res is True and store.get(q.id).resolution == "us-east-1"


def test_freetext_answer_containing_decision_substrings_stays_freetext(tmp_path):
    """Decision intent comes from the LEADING word only — a free-text answer that merely
    contains "no"/"yes" as a substring or mid-sentence word must not flip to deny/allow."""
    store = InboxStore(tmp_path / "inbox.json")
    for answer in (
        "I have no preference — use us-east-1",
        "yesterday's numbers look fine",
        "the northern region",
    ):
        q = store.add_question("s1", "Which region?")
        assert resolve_from_reply(f"{answer} [ow:{q.id}]", store.resolve) is True
        assert store.get(q.id).resolution == answer


def test_negated_approval_reply_does_not_allow(tmp_path):
    """"I cannot approve this yet" used to resolve as ALLOW (substring match, allow words
    checked first). It must fall through to free text, which the approver maps to deny."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Deploy?", inbox="ops")
    assert resolve_from_reply(f"I cannot approve this yet [ow:{item.id}]", store.resolve)
    assert store.get(item.id).resolution == "I cannot approve this yet"


def test_leading_decision_word_and_emoji_still_resolve(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    for reply, expected in (
        ("Yes, go ahead", "allow"),
        ("No.", "deny"),
        ("👍", "allow"),
        ("❌ too risky", "deny"),
        ("allow", "allow"),
        ("reject", "deny"),
    ):
        item = store.add_approval("s1", "Deploy?", inbox="ops")
        assert resolve_from_reply(f"{reply} [ow:{item.id}]", store.resolve) is True
        assert store.get(item.id).resolution == expected


def test_decision_word_after_token_still_resolves(tmp_path):
    """The [ow:…] token may lead the reply (e.g. a quoted redelivery) — intent is parsed
    from the text with the token stripped, wherever it sits."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Deploy?", inbox="ops")
    assert resolve_from_reply(f"[ow:{item.id}] approve", store.resolve) is True
    assert store.get(item.id).resolution == "allow"


def test_reply_without_token_is_ignored(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    assert resolve_from_reply("random chatter", store.resolve) is None


def test_inbound_legacy_ocw_token_still_resolves(tmp_path):
    """Replies to messages sent BEFORE the @OpenWorker rename carry [ocw:…] — must keep working."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Deploy?", inbox="ops")
    assert resolve_from_reply(f"deny [ocw:{item.id}]", store.resolve) is True
    assert store.get(item.id).resolution == "deny"


def test_disallow_is_not_parsed_as_allow(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_approval("s1", "Deploy?", inbox="ops")
    assert resolve_from_reply(f"disallow [ow:{item.id}]", store.resolve) is True
    assert store.get(item.id).resolution != "allow"


def test_words_containing_no_are_not_parsed_as_deny(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    q = store.add_question("s1", "Which region?")
    assert resolve_from_reply(f"north-east node [ow:{q.id}]", store.resolve) is True
    assert store.get(q.id).resolution == "north-east node"


def test_denied_and_approved_word_forms(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    a = store.add_approval("s1", "Deploy?", inbox="ops")
    b = store.add_approval("s1", "Restart?", inbox="ops")
    resolve_from_reply(f"denied [ow:{a.id}]", store.resolve)
    resolve_from_reply(f"approved [ow:{b.id}]", store.resolve)
    assert store.get(a.id).resolution == "deny"
    assert store.get(b.id).resolution == "allow"


def test_emoji_reactions_still_resolve(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    a = store.add_approval("s1", "Deploy?", inbox="ops")
    b = store.add_approval("s1", "Restart?", inbox="ops")
    resolve_from_reply(f"👍 [ow:{a.id}]", store.resolve)
    resolve_from_reply(f"❌ [ow:{b.id}]", store.resolve)
    assert store.get(a.id).resolution == "allow"
    assert store.get(b.id).resolution == "deny"


# -- numbered replies (the WeChat card) -----------------------------------------
_APPROVAL_CHOICES = [
    Choice("Approve", "allow", "allow"),
    Choice("Deny", "deny", "deny"),
]


def test_choice_number_selects_by_position():
    assert choice_from_reply("1", _APPROVAL_CHOICES) == "allow"
    assert choice_from_reply("2", _APPROVAL_CHOICES) == "deny"
    assert choice_from_reply("回复 2", _APPROVAL_CHOICES) == "deny"
    assert choice_from_reply("1.", _APPROVAL_CHOICES) == "allow"
    assert choice_from_reply("2、", _APPROVAL_CHOICES) == "deny"


def test_fullwidth_digits_from_a_phone_keyboard_still_select():
    assert choice_from_reply("１", _APPROVAL_CHOICES) == "allow"
    assert choice_from_reply("２", _APPROVAL_CHOICES) == "deny"
    assert to_halfwidth("１２３") == "123"


def test_chinese_decision_words_map_to_the_matching_choice():
    for reply in ("同意", "允许", "批准", "可以", "同意。"):
        assert choice_from_reply(reply, _APPROVAL_CHOICES) == "allow", reply
    for reply in ("拒绝", "不行", "取消", "否", "拒绝！"):
        assert choice_from_reply(reply, _APPROVAL_CHOICES) == "deny", reply


def test_number_outside_the_offered_range_is_not_an_answer():
    """"5" against a two-option card is a miss, not a free-text answer — handing the agent a
    bare 5 would be worse than asking again."""
    assert choice_from_reply("5", _APPROVAL_CHOICES) is None
    assert choice_from_reply("5", [Choice("A", "A")], allow_text=True) is None


def test_freetext_is_an_answer_only_where_the_prompt_accepts_one():
    options = [Choice("us-east-1", "us-east-1"), Choice("eu-west-1", "eu-west-1")]
    assert choice_from_reply("tokyo please", options) is None
    assert choice_from_reply("tokyo please", options, allow_text=True) == "tokyo please"
    # An option typed out verbatim selects it even without the number.
    assert choice_from_reply("eu-west-1", options) == "eu-west-1"


def test_unreadable_reply_to_a_gate_is_none():
    assert choice_from_reply("这是什么？", _APPROVAL_CHOICES) is None
    assert choice_from_reply("", _APPROVAL_CHOICES) is None
    assert choice_from_reply("   ", _APPROVAL_CHOICES) is None


def test_is_choice_number_spots_a_bare_digit_reply():
    assert is_choice_number("1") and is_choice_number("２") and is_choice_number("回复 1")
    assert not is_choice_number("1 同意")
    assert not is_choice_number("同意")
    assert not is_choice_number("")
