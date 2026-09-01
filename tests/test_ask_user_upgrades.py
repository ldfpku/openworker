"""OPE-51 — ask_user upgrades: rich options ({label, description, recommended, preview}),
grouped questions (one call, a stepper, one round-trip), and the {answer}/{answers} result
shapes. Back-compat is load-bearing: plain-string options and old persisted items must be
untouched by all of it."""

import asyncio
import json

from coworker.inbox import InboxItem, InboxStore
from coworker.interactions import buttons_for, decode
from coworker.server.manager import SessionManager
from coworker.tools.ask import (
    MAX_GROUPED_QUESTIONS,
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
    assert [b.label for b in btns] == ["staging", "prod"]
    assert decode(btns[1].value) == (item.id, "prod")  # resolution IS the label


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
    assert [b.label for b in btns] == ["staging", "prod"]
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
