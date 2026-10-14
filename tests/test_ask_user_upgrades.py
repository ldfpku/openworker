"""OPE-51 — ask_user upgrades: rich options ({label, description, recommended, preview}),
grouped questions (one call, a stepper, one round-trip), and the {answer}/{answers} result
shapes. Back-compat is load-bearing: plain-string options and old persisted items must be
untouched by all of it."""

import asyncio
import json

from coworker.engine import TurnEngine
from coworker.inbox import InboxItem, InboxStore
from coworker.inbox_routing import choice_from_reply
from coworker.interactions import (
    buttons_for,
    choices_for,
    decode,
    deny_resolution,
    outcome_text,
    weixin_prompt,
)
from coworker.server.manager import SessionManager
from coworker.tools.ask import (
    MAX_GROUPED_QUESTIONS,
    PREFLIGHT_SKIP,
    SKIP_NOTE,
    SKIP_SENTINEL,
    answer_result,
    ask_user_tool,
    normalize_option,
    normalize_questions,
    option_label,
    question_item_fields,
)

from test_durable_resume import ScriptedProvider, _run_until_pending, _text, _tool


# -- schema -------------------------------------------------------------------


def test_schema_advertises_only_the_grouped_questions_form():
    fn = ask_user_tool().__coworker_schema__["function"]
    assert fn["name"] == "ask_user"
    props = fn["parameters"]["properties"]
    # Only `questions` is advertised — no singular question/options/allow_text/multi/header
    # left over at the top level (a single question is just a one-item `questions` array).
    assert set(props) == {"questions"}
    assert fn["parameters"]["required"] == ["questions"]
    # grouped: capped, each entry requires `question`
    grouped = props["questions"]
    assert grouped["minItems"] == 1
    assert grouped["maxItems"] == MAX_GROUPED_QUESTIONS
    item_props = grouped["items"]["properties"]
    assert grouped["items"]["required"] == ["question"]
    assert set(item_props) == {"question", "header", "options", "allow_text", "multi"}
    # options (nested under each question now): string-or-object union, object requires `label`
    variants = item_props["options"]["items"]["anyOf"]
    assert {"type": "string"} in variants
    obj = next(v for v in variants if v.get("type") == "object")
    assert obj["required"] == ["label"]
    assert set(obj["properties"]) == {"label", "description", "recommended", "preview"}


def test_schema_size_guardrail():
    # The biggest tool schema in the registry — keep it lean. json.dumps ≈ token count.
    assert len(json.dumps(ask_user_tool().__coworker_schema__)) < 1400


# -- normalization helpers ----------------------------------------------------


def test_normalize_option_and_label():
    assert normalize_option("Bar") == {
        "label": "Bar",
        "description": "",
        "recommended": False,
        "preview": "",
    }
    rich = normalize_option({"label": "Line", "recommended": True, "preview": "p"})
    assert rich["recommended"] is True and rich["preview"] == "p"
    assert option_label("Bar") == "Bar" and option_label({"label": "Line"}) == "Line"


def test_normalize_questions_caps_and_drops_blanks():
    entries = [{"question": f"Q{i}?"} for i in range(MAX_GROUPED_QUESTIONS + 2)]
    assert len(normalize_questions(entries)) == MAX_GROUPED_QUESTIONS
    assert normalize_questions([{"question": "  "}, "junk", {"header": "h"}]) == []


def test_question_item_fields_plain_strings_pass_through():
    fields = question_item_fields({"question": "Env?", "options": ["staging", "prod"]})
    assert fields["title"] == "Env?"
    assert fields["options"] == ["staging", "prod"]  # simple asks stay today's pills
    assert fields["questions"] == []


def test_question_item_fields_rich_options_canonicalized():
    fields = question_item_fields(
        {"question": "Env?", "options": [{"label": "staging", "recommended": True}]}
    )
    assert fields["options"] == [
        {"label": "staging", "description": "", "recommended": True, "preview": ""}
    ]


def test_question_item_fields_singleton_group_matches_legacy_singular_form():
    # Since the schema now only ever advertises `questions`, the model sends a one-item array
    # even for a lone question. Its title/options must land the same as the old singular form
    # (`question`/`options` at the top level) — the two are equivalent, not a stepper of 1.
    grouped = question_item_fields(
        {"questions": [{"question": "Env?", "options": ["staging", "prod"]}]}
    )
    singular = question_item_fields({"question": "Env?", "options": ["staging", "prod"]})
    assert grouped["title"] == singular["title"] == "Env?"
    # `normalize_questions` canonicalizes every option (grouped path always does, even a
    # singleton group); the singular path leaves plain strings untouched. Different shape, same
    # answer values — compare by label, which is what surfaces actually render/answer with.
    assert [o["label"] for o in grouped["options"]] == singular["options"] == ["staging", "prod"]
    assert grouped["allow_text"] == singular["allow_text"]
    assert grouped["header"] == singular["header"] == ""
    # The only real difference: the grouped item also carries the full `questions` list (length
    # 1), which is what tells surfaces whether to key the answer as {"answer"} or {"answers"}.
    assert len(grouped["questions"]) == 1 and singular["questions"] == []


def test_question_item_fields_grouped_surfaces_first_question():
    fields = question_item_fields(
        {
            "questions": [
                {"question": "Chart style?", "header": "Chart", "options": ["Bar"]},
                {"question": "Colors?", "multi": True},
            ]
        }
    )
    assert fields["title"] == "Chart style?" and fields["header"] == "Chart"
    assert fields["options"][0]["label"] == "Bar"
    assert len(fields["questions"]) == 2 and fields["questions"][1]["multi"] is True


def test_question_item_fields_nothing_asked():
    assert question_item_fields({}) is None
    assert question_item_fields({"question": "  "}) is None
    assert question_item_fields({"questions": [{"question": ""}]}) is None


# -- result shaping -----------------------------------------------------------


def test_answer_result_shapes():
    assert answer_result([], "staging") == {"answer": "staging"}
    assert answer_result([], None) == {"answer": ""}
    grouped = [{"question": "Chart style?", "header": "Chart"}, {"question": "Colors?"}]
    res = answer_result(grouped, json.dumps({"Chart": "Bar", "Colors?": "Blue"}))
    assert res == {"answers": {"Chart": "Bar", "Colors?": "Blue"}}
    # a text-only surface answered with a bare string → attributed to the first question
    assert answer_result(grouped, "Bar") == {"answers": {"Chart": "Bar"}}
    assert answer_result(grouped, "") == {"answer": ""}  # engine reads this as denied


# -- skipping (OPE-153) -------------------------------------------------------


def test_skipped_single_question_answers_null_not_empty():
    """The whole point of the sentinel: "" (no answer came back) and a skip must not
    look alike to the agent."""
    res = answer_result([], SKIP_SENTINEL)
    assert res["answer"] is None
    assert res["skipped"] is True
    assert res["note"] == SKIP_NOTE
    assert answer_result([], "") == {"answer": ""}  # unchanged, still not a skip


def test_skipped_grouped_questions_name_what_was_declined():
    grouped = [{"question": "Chart style?", "header": "Chart"}, {"question": "Colors?"}]
    # one step skipped, one answered
    res = answer_result(grouped, json.dumps({"Chart": SKIP_SENTINEL, "Colors?": "Blue"}))
    assert res["answers"] == {"Chart": None, "Colors?": "Blue"}
    assert res["skipped"] == ["Chart"]
    assert res["note"] == SKIP_NOTE
    # whole card skipped from the card: every question carries the sentinel
    res = answer_result(grouped, json.dumps({"Chart": SKIP_SENTINEL, "Colors?": SKIP_SENTINEL}))
    assert res["answers"] == {"Chart": None, "Colors?": None}
    assert res["skipped"] == ["Chart", "Colors?"]
    # a JSON null means the same thing (defensive — a surface may serialize it that way)
    assert answer_result(grouped, json.dumps({"Chart": None}))["skipped"] == ["Chart"]
    # a multi-select answer next to a skip still comes back as a list (the comma fix)
    res = answer_result(grouped, json.dumps({"Chart": SKIP_SENTINEL, "Colors?": ["a, b", "c"]}))
    assert res["answers"] == {"Chart": None, "Colors?": ["a, b", "c"]}


def test_bare_sentinel_skips_a_whole_grouped_card():
    """A text-only surface can't send the answer map — the bare sentinel skips everything
    rather than being filed as the first question's answer."""
    grouped = [{"question": "Chart style?", "header": "Chart"}, {"question": "Colors?"}]
    res = answer_result(grouped, SKIP_SENTINEL)
    assert res["answers"] == {"Chart": None, "Colors?": None}
    assert res["skipped"] == ["Chart", "Colors?"]


def test_fully_answered_card_carries_no_skip_keys():
    """No skip → no `skipped`/`note` noise in the agent's tool result."""
    grouped = [{"question": "Chart style?", "header": "Chart"}]
    assert answer_result(grouped, json.dumps({"Chart": "Bar"})) == {"answers": {"Chart": "Bar"}}
    assert answer_result([], "staging") == {"answer": "staging"}


def test_preflight_skip_stays_its_own_sentinel():
    """The 开工前核对 card's 「跳过，按默认口径直接做」 is not an OPE-153 skip: it carries no
    note and no null answers — the brief it renders already says to proceed on defaults."""
    grouped = [{"question": "交付什么？", "header": "要什么"}]
    assert answer_result(grouped, PREFLIGHT_SKIP) == {"answers": {}, "skipped": True}
    assert "note" not in answer_result([], PREFLIGHT_SKIP)


def test_skipped_answers_are_not_filed_as_user_replies():
    """A skipped question answers None; the reviewer's history must not record "None"
    (or anything) as something the user said."""
    eng = TurnEngine.__new__(TurnEngine)
    eng.messages = []
    eng._ask_replies = []
    eng._reviewer_denials = 2
    eng._note_ask_replies({"answers": {"Chart": None, "Colors?": "Blue"}, "skipped": ["Chart"]}, "q")
    assert [t for _, t, _ in eng._ask_replies] == ["Blue"]
    eng._note_ask_replies({"answer": None, "skipped": True}, "q")
    assert [t for _, t, _ in eng._ask_replies] == ["Blue"]
    assert eng._reviewer_denials == 0


# -- inbox persistence + back-compat ------------------------------------------


def test_inbox_round_trips_grouped_questions(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    fields = question_item_fields(
        {
            "questions": [
                {
                    "question": "Format?",
                    "header": "Format",
                    "options": [{"label": "Table", "preview": "| a | b |"}],
                },
                {"question": "Where to?"},
            ]
        }
    )
    item = store.add_question("s1", **fields)
    reloaded = InboxStore(tmp_path / "inbox.json").get(item.id)
    assert reloaded.header == "Format"
    assert reloaded.questions == item.questions
    assert reloaded.options[0]["preview"] == "| a | b |"


def test_old_persisted_items_still_load():
    # Items written before OPE-51 carry no header/questions keys and string options.
    old = InboxItem(
        id="x", session_id="s", kind="question", title="Env?", options=["staging"]
    )
    assert old.header == "" and old.questions == []


# -- channel buttons ----------------------------------------------------------


def test_buttons_use_rich_option_labels(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question(
        "s1",
        "Env?",
        options=["staging", {"label": "prod", "description": "the real one"}],
    )
    btns = buttons_for(item)
    assert [b.label for b in btns] == ["staging", "prod", "Skip"]
    assert decode(btns[1].value) == (item.id, "prod")  # resolution IS the label


def test_mirrored_question_offers_a_skip_button(tmp_path):
    """OPE-153 — the channel gets the same way out the card has. Skip trails the options and
    carries the sentinel, which answer_result() turns into a null answer."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "Env?", options=["staging", "prod"])
    skip = buttons_for(item)[-1]
    assert skip.label == "Skip"
    assert decode(skip.value) == (item.id, SKIP_SENTINEL)
    # and that resolution is what the agent ends up seeing
    assert answer_result(item.questions, SKIP_SENTINEL)["answer"] is None


def test_questions_without_options_get_no_buttons(tmp_path):
    """A free-text question still mirrors as plain text — no lone Skip button, since the
    "(Open the app to respond.)" fallback is the only way to answer it at all."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "What should I name it?")
    assert buttons_for(item) == []


def test_weixin_card_numbers_the_skip_and_reads_it_back(tmp_path):
    """The WeChat card is derived from the same choices: Skip is the last number, worded 跳过,
    a typed 跳过/skip lands on it instead of riding in as a free-text answer, and the receipt
    says 跳过 rather than the sentinel."""
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", "Env?", options=["staging", "prod"])
    choices = choices_for(item)
    assert [(c.label, c.intent) for c in choices] == [("staging", None), ("prod", None), ("Skip", "skip")]
    card = weixin_prompt(item, 30)
    assert "1 staging\n2 prod\n3 跳过" in card
    assert choice_from_reply("3", choices, allow_text=True) == SKIP_SENTINEL
    assert choice_from_reply("跳过", choices, allow_text=True) == SKIP_SENTINEL
    assert choice_from_reply("skip", choices, allow_text=True) == SKIP_SENTINEL
    assert choice_from_reply("拒绝", choices, allow_text=True) == "拒绝"  # a deny word is NOT a skip
    assert outcome_text(item, SKIP_SENTINEL) == "跳过"
    free = store.add_question("s1", "Name?")
    assert outcome_text(free, SKIP_SENTINEL) == "跳过"  # skipped in the app: no choices to match


def test_expired_question_is_skipped_not_answered_deny(tmp_path):
    """The WeChat watchdog's fallback used to answer a question with the literal text "deny";
    a question has nothing to deny, so it is skipped — grouped and free-text ones included —
    and the engine's own pre-flight card falls back to its own "proceed on defaults"."""
    store = InboxStore(tmp_path / "inbox.json")
    assert deny_resolution(store.add_question("s1", "Env?", options=["a", "b"])) == SKIP_SENTINEL
    assert deny_resolution(store.add_question("s1", "Name?")) == SKIP_SENTINEL
    grouped = store.add_question(
        "s1", **question_item_fields({"questions": [{"question": "A?"}, {"question": "B?"}]})
    )
    assert deny_resolution(grouped) == SKIP_SENTINEL
    assert answer_result(grouped.questions, SKIP_SENTINEL)["answers"] == {"A?": None, "B?": None}
    pre = store.add_question(
        "s1", tool_call_id="preflight:1", **question_item_fields({"question": "交付什么？", "options": ["Word"]}, preflight=True)
    )
    assert deny_resolution(pre) == PREFLIGHT_SKIP
    assert choices_for(pre)[-1].resolution == PREFLIGHT_SKIP
    assert deny_resolution(store.add_approval("s1", "Run it?")) == "deny"  # approvals unchanged


def test_grouped_questions_get_no_buttons(tmp_path):
    store = InboxStore(tmp_path / "inbox.json")
    fields = question_item_fields(
        {"questions": [{"question": "A?", "options": ["x"]}, {"question": "B?"}]}
    )
    item = store.add_question("s1", **fields)
    assert buttons_for(item) == []  # one button row can't answer 2+ questions


def test_singleton_question_group_still_gets_buttons(tmp_path):
    # The schema now only advertises `questions`, so a lone question also arrives as a
    # one-item array — it must keep getting channel buttons, same as the old singular form
    # (only 2+ questions fall back to plain text; see the test above).
    store = InboxStore(tmp_path / "inbox.json")
    fields = question_item_fields(
        {"questions": [{"question": "Env?", "options": ["staging", "prod"]}]}
    )
    item = store.add_question("s1", **fields)
    btns = buttons_for(item)
    assert [b.label for b in btns] == ["staging", "prod", "Skip"]
    assert decode(btns[0].value) == (item.id, "staging")


# -- full stack: grouped call → Inbox item → JSON resolution → {answers} ------


def test_grouped_ask_round_trip_through_manager(tmp_path):
    mgr = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [
                _tool(
                    "ask_user",
                    {
                        "questions": [
                            {
                                "question": "Chart style?",
                                "header": "Chart",
                                "options": [
                                    {"label": "Bar", "recommended": True},
                                    "Line",
                                ],
                            },
                            {"question": "Which distribution?", "header": "Distribution"},
                        ]
                    },
                    "call_g",
                ),
                _text("Bar it is, stacked."),
            ]
        ),
    )
    sid = "grouped-q"

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        assert item.kind == "question" and item.tool_call_id == "call_g"
        assert item.title == "Chart style?" and len(item.questions) == 2
        await mgr.resolve_inbox(
            item.id, json.dumps({"Chart": "Bar", "Distribution": "Stacked"})
        )

    asyncio.run(scenario())
    # The tool result the model saw carries the parsed answers map.
    rec = mgr.session_store.load(sid)
    tool_msgs = [m for m in rec.messages if m.get("role") == "tool"]
    assert tool_msgs, "no tool result was recorded"
    payload = json.loads(tool_msgs[-1]["content"])
    assert payload == {"answers": {"Chart": "Bar", "Distribution": "Stacked"}}
    assert mgr.inbox.pending(sid) == []


# -- multi-select answers are lists; the pre-flight skip sentinel --------------------


def test_answer_result_turns_json_arrays_into_lists_and_keeps_legacy_strings():
    from coworker.tools.ask import PREFLIGHT_SKIP

    grouped = [{"question": "Sources?", "header": "依据在哪", "multi": True}, {"question": "Who?", "header": "给谁看"}]
    out = answer_result(grouped, json.dumps({"依据在哪": ["检验记录, 机加", "处理单"], "给谁看": "部长"}))
    assert out == {"answers": {"依据在哪": ["检验记录, 机加", "处理单"], "给谁看": "部长"}}
    # a lone multi question resolves with the whole array JSON-encoded
    assert answer_result([], json.dumps(["a, b", "c"])) == {"answer": ["a, b", "c"]}
    assert answer_result(grouped, json.dumps({"依据在哪": json.dumps(["x", "y"])}))["answers"]["依据在哪"] == ["x", "y"]
    # legacy comma-joined strings and plain text are untouched
    assert answer_result([], "a, b") == {"answer": "a, b"}
    assert answer_result(grouped, "plain reply") == {"answers": {"依据在哪": "plain reply"}}
    assert answer_result([], "[not json") == {"answer": "[not json"}
    # the skip sentinel: no answers, flagged, whatever the item shape
    assert answer_result(grouped, PREFLIGHT_SKIP) == {"answers": {}, "skipped": True}
    assert answer_result([], PREFLIGHT_SKIP) == {"answers": {}, "skipped": True}


def test_question_item_fields_marks_preflight_only_when_told(tmp_path):
    args = {"questions": [{"question": "交付什么？", "header": "要什么", "options": ["Word"]}]}
    assert "data" not in question_item_fields(args)
    assert "data" not in question_item_fields({**args, "preflight": True})  # args never decide
    fields = question_item_fields(args, preflight=True)
    assert fields["data"] == {"preflight": True}
    single = question_item_fields({"question": "Env?", "options": ["a"]}, preflight=True)
    assert single["data"] == {"preflight": True}
    store = InboxStore(tmp_path / "inbox.json")
    item = store.add_question("s1", tool_call_id="preflight:1", **fields)
    assert item.data == {"preflight": True}
    assert store.add_question("s1", tool_call_id="preflight:1", **fields).id == item.id  # idempotent
