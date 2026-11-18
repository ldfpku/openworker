"""Streaming tool-call assembly in `OpenAIProvider.stream()` (spec: skill-invocation-error-fix).

Gemini's OpenAI-compatible stream (via Cloudflare AI Gateway `/compat`) emits parallel tool
calls whose deltas carry NO `index` (the SDK reads it as `None`). Each model-emitted call must
still come out as its own `ToolCall`, with its own id, name and arguments, in emission order.

SDK-free: fake chunks are `SimpleNamespace`s, as in `tests/test_providers.py`. Property-style
cases use `random.Random(seed)` + `parametrize` (the project does not depend on hypothesis).
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest

from coworker.providers import OpenAIProvider, ToolCall


# -- fakes ----------------------------------------------------------------------


def _delta(index=None, id=None, name=None, args=None):
    """One SDK tool-call delta. `index=None` is how the SDK surfaces a missing index."""
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=args)
    )


def _chunk(content=None, tool_call=None, finish=None):
    delta = SimpleNamespace(
        content=content, tool_calls=[tool_call] if tool_call else None
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


class _StreamClient:
    def __init__(self, chunks):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: iter(chunks))
        )


def _final_turn(deltas):
    chunks = [_chunk(tool_call=d) for d in deltas] + [_chunk(finish="tool_calls")]
    provider = OpenAIProvider(client=_StreamClient(chunks))
    return list(provider.stream(model="google-ai-studio/gemini-x", messages=[]))[-1].turn


def _parse_or_raw(text):
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"_raw": text}


# -- Property 1: concrete counterexamples ---------------------------------------
# **Validates: Requirements 1.1, 1.2, 2.1, 2.2**


def test_gemini_live_shape_load_skill_plus_todo_write_are_separate_calls():
    deltas = [
        _delta(id="c1", name="load_skill", args='{"name": "pdf-translate-zh"}'),
        _delta(id="c2", name="todo_write", args='{"todos": []}'),
    ]
    turn = _final_turn(deltas)
    assert turn.tool_calls == [
        ToolCall(id="c1", name="load_skill", arguments={"name": "pdf-translate-zh"}),
        ToolCall(id="c2", name="todo_write", arguments={"todos": []}),
    ]


def test_fragmented_arguments_without_index_then_second_call():
    deltas = [
        _delta(id="c1", name="read_file", args='{"pa'),
        _delta(args='th": "a.py"}'),
        _delta(id="c2", name="grep", args='{"pattern": "x"}'),
    ]
    turn = _final_turn(deltas)
    assert turn.tool_calls == [
        ToolCall(id="c1", name="read_file", arguments={"path": "a.py"}),
        ToolCall(id="c2", name="grep", arguments={"pattern": "x"}),
    ]


def test_three_parallel_calls_without_index():
    deltas = [
        _delta(id="c1", name="read_file", args='{"path": "a.py"}'),
        _delta(id="c2", name="read_file", args='{"path": "b.py"}'),
        _delta(id="c3", name="grep", args='{"pattern": "TODO"}'),
    ]
    turn = _final_turn(deltas)
    assert turn.tool_calls == [
        ToolCall(id="c1", name="read_file", arguments={"path": "a.py"}),
        ToolCall(id="c2", name="read_file", arguments={"path": "b.py"}),
        ToolCall(id="c3", name="grep", arguments={"pattern": "TODO"}),
    ]


def test_mixed_index_keeps_both_calls_indexed_first():
    deltas = [
        _delta(index=0, id="c1", name="load_skill", args='{"name": "pdf-translate-zh"}'),
        _delta(index=None, id="c2", name="todo_write", args='{"todos": []}'),
    ]
    turn = _final_turn(deltas)
    assert turn.tool_calls == [
        ToolCall(id="c1", name="load_skill", arguments={"name": "pdf-translate-zh"}),
        ToolCall(id="c2", name="todo_write", arguments={"todos": []}),
    ]


# -- Property 1: randomized ------------------------------------------------------
# **Validates: Requirements 1.1, 1.2, 2.1, 2.2**

_TOOL_NAMES = ["load_skill", "todo_write", "read_file", "grep", "write_file", "bash"]
_KEYS = ["name", "path", "pattern", "todos", "content", "command", "limit"]


def _random_value(rng):
    kind = rng.randrange(5)
    if kind == 0:
        return rng.randrange(-50, 500)
    if kind == 1:
        return rng.choice(["a.py", "x", "pdf-translate-zh", "D:\\SMJ\\f 1.pdf", "", "中文"])
    if kind == 2:
        return rng.choice([True, False, None])
    if kind == 3:
        return [rng.randrange(10) for _ in range(rng.randrange(3))]
    return {"k": rng.choice(["v", "w"]), "n": rng.randrange(3)}


def _random_args_text(rng):
    keys = rng.sample(_KEYS, rng.randint(1, 3))
    return json.dumps({k: _random_value(rng) for k in keys}, ensure_ascii=False)


def _split(rng, text):
    """Cut `text` into 1–4 non-empty fragments."""
    pieces = rng.randint(1, min(4, len(text)))
    cuts = sorted(rng.sample(range(1, len(text)), pieces - 1))
    bounds = [0, *cuts, len(text)]
    return [text[a:b] for a, b in zip(bounds, bounds[1:])]


def _random_calls(rng, *, with_ids):
    count = rng.randint(2, 4)
    calls = []
    for k in range(count):
        if with_ids:
            name = rng.choice(_TOOL_NAMES)
        else:
            # id-less streams are only separable when adjacent calls differ by name
            prev = calls[-1]["name"] if calls else None
            name = rng.choice([n for n in _TOOL_NAMES if n != prev])
        calls.append(
            {
                "id": f"call_{k}_{rng.randrange(10**6)}" if with_ids else "",
                "name": name,
                "args": _random_args_text(rng),
            }
        )
    return calls


def _deltas_for(rng, calls, *, with_ids):
    deltas = []
    for call in calls:
        repeat_id = with_ids and rng.random() < 0.5
        for i, frag in enumerate(_split(rng, call["args"])):
            first = i == 0
            deltas.append(
                _delta(
                    index=None,
                    id=call["id"] if with_ids and (first or repeat_id) else None,
                    name=call["name"] if first else None,
                    args=frag,
                )
            )
    return deltas


def _assert_matches(turn, calls):
    assert len(turn.tool_calls) == len(calls), (
        f"expected {len(calls)} calls, got {turn.tool_calls!r}"
    )
    for got, want in zip(turn.tool_calls, calls):
        assert got.id == want["id"]
        assert got.name == want["name"]
        assert got.arguments == _parse_or_raw(want["args"])


@pytest.mark.parametrize("seed", range(40))
def test_random_parallel_calls_without_index_with_ids(seed):
    rng = random.Random(seed)
    calls = _random_calls(rng, with_ids=True)
    turn = _final_turn(_deltas_for(rng, calls, with_ids=True))
    _assert_matches(turn, calls)


@pytest.mark.parametrize("seed", range(40))
def test_random_parallel_calls_without_index_or_ids(seed):
    rng = random.Random(1000 + seed)
    calls = _random_calls(rng, with_ids=False)
    turn = _final_turn(_deltas_for(rng, calls, with_ids=False))
    _assert_matches(turn, calls)


# -- Property 2: Preservation ----------------------------------------------------
# Inputs where the bug condition does NOT hold (every delta carries an explicit index, at
# most one tool call, or no tool calls at all) must assemble exactly as before the fix.
# `_legacy_tool_calls` is a verbatim copy of the pre-fix `tool_accum` logic in
# `OpenAIProvider.stream()` and serves as the reference implementation.
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.9**


def _legacy_tool_calls(deltas):
    """Pre-fix `stream()` tool-call assembly, copied as-is (openai_provider.py ~459, 494–522)."""
    tool_accum = {}
    for tc in deltas:
        acc = tool_accum.setdefault(
            getattr(tc, "index", 0), {"id": "", "name": "", "args": ""}
        )
        if getattr(tc, "id", None):
            acc["id"] = tc.id
        fn = getattr(tc, "function", None)
        if fn is not None:
            if getattr(fn, "name", None):
                acc["name"] = fn.name
            if getattr(fn, "arguments", None):
                acc["args"] += fn.arguments

    tool_calls = []
    for index in sorted(tool_accum):
        acc = tool_accum[index]
        try:
            arguments = json.loads(acc["args"]) if acc["args"] else {}
        except (TypeError, json.JSONDecodeError):
            arguments = {"_raw": acc["args"]}
        tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=arguments))
    return tool_calls


def _stream_out(chunks, *, model="gpt-5.5", tools=None):
    provider = OpenAIProvider(client=_StreamClient(chunks))
    return list(provider.stream(model=model, messages=[], tools=tools))


# -- Property 2: concrete baseline (observed on unfixed code) ---------------------


def test_indexed_calls_interleaved_are_grouped_by_index():
    deltas = [
        _delta(index=0, id="c0", name="read_file", args='{"pa'),
        _delta(index=1, id="c1", name="grep", args='{"pat'),
        _delta(index=0, args='th": "a.py"}'),
        _delta(index=1, args='tern": "x"}'),
    ]
    expected = [
        ToolCall(id="c0", name="read_file", arguments={"path": "a.py"}),
        ToolCall(id="c1", name="grep", arguments={"pattern": "x"}),
    ]
    assert _legacy_tool_calls(deltas) == expected
    assert _final_turn(deltas).tool_calls == expected


def test_indexed_calls_arriving_one_before_zero_come_out_in_index_order():
    deltas = [
        _delta(index=1, id="c1", name="grep", args='{"pattern": "x"}'),
        _delta(index=0, id="c0", name="read_file", args='{"path": '),
        _delta(index=0, args='"a.py"}'),
    ]
    expected = [
        ToolCall(id="c0", name="read_file", arguments={"path": "a.py"}),
        ToolCall(id="c1", name="grep", arguments={"pattern": "x"}),
    ]
    assert _legacy_tool_calls(deltas) == expected
    assert _final_turn(deltas).tool_calls == expected


@pytest.mark.parametrize("index", [0, None])
@pytest.mark.parametrize("call_id", ["c1", None])
@pytest.mark.parametrize("fragments", [['{"todos": []}'], ['{"to', 'dos": ', "[]}"]])
def test_single_call_with_or_without_index_and_id(index, call_id, fragments):
    deltas = [
        _delta(index=index, id=call_id if i == 0 else None,
               name="todo_write" if i == 0 else None, args=frag)
        for i, frag in enumerate(fragments)
    ]
    expected = [ToolCall(id=call_id or "", name="todo_write", arguments={"todos": []})]
    assert _legacy_tool_calls(deltas) == expected
    assert _final_turn(deltas).tool_calls == expected


@pytest.mark.parametrize("index", [0, None])
@pytest.mark.parametrize("bad", ['{"path": "a.py"', '{"a":1}}'])
def test_single_call_with_malformed_json_stays_raw(index, bad):
    deltas = [_delta(index=index, id="c1", name="read_file", args=bad)]
    expected = [ToolCall(id="c1", name="read_file", arguments={"_raw": bad})]
    assert _legacy_tool_calls(deltas) == expected
    assert _final_turn(deltas).tool_calls == expected


def test_malformed_json_cut_by_token_limit_keeps_finish_reason_length():
    chunks = [
        _chunk(tool_call=_delta(index=0, id="c1", name="write_file", args='{"path": "a.py", "con')),
        _chunk(finish="length"),
    ]
    turn = _stream_out(chunks)[-1].turn
    assert turn.tool_calls == [
        ToolCall(id="c1", name="write_file", arguments={"_raw": '{"path": "a.py", "con'})
    ]
    assert turn.finish_reason == "length"
    assert turn.truncated is False


def test_plain_text_stream_without_tool_calls_is_unchanged():
    out = _stream_out([_chunk(content="Hel"), _chunk(content="lo"), _chunk(finish="stop")])
    assert [c.text_delta for c in out if c.text_delta] == ["Hel", "lo"]
    turn = out[-1].turn
    assert turn.text == "Hello"
    assert turn.tool_calls == []
    assert turn.finish_reason == "stop"
    assert turn.truncated is False


_READ_FILE_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
]


def test_text_salvage_path_still_recovers_tool_call_from_text():
    text = '<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
    out = _stream_out(
        [_chunk(content=text[:20]), _chunk(content=text[20:]), _chunk(finish="stop")],
        tools=_READ_FILE_SCHEMA,
    )
    assert [c.text_delta for c in out if c.text_delta] == [text[:20], text[20:]]
    turn = out[-1].turn
    assert turn.text is None
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [
        ("read_file", {"path": "a.py"})
    ]


def test_non_streaming_complete_parses_two_calls_separately():
    tcs = [
        SimpleNamespace(id="c1", function=SimpleNamespace(
            name="load_skill", arguments='{"name": "pdf-translate-zh"}')),
        SimpleNamespace(id="c2", function=SimpleNamespace(
            name="todo_write", arguments='{"todos": []}')),
    ]
    message = SimpleNamespace(content=None, tool_calls=tcs)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response))
    )
    turn = OpenAIProvider(client=client).complete(model="gpt-5.5", messages=[])
    assert turn.tool_calls == [
        ToolCall(id="c1", name="load_skill", arguments={"name": "pdf-translate-zh"}),
        ToolCall(id="c2", name="todo_write", arguments={"todos": []}),
    ]


class _ClosableWire:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = 0

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        self.closed += 1


def test_finish_reason_usage_and_close_stream_are_unchanged():
    wire = _ClosableWire(
        [
            _chunk(tool_call=_delta(index=0, id="c1", name="grep", args='{"pattern": "x"}')),
            _chunk(finish="tool_calls"),
            # usage arrives on a final chunk with empty choices
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
            ),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: wire))
    )
    out = list(OpenAIProvider(client=client).stream(model="gpt-5.5", messages=[]))
    turn = out[-1].turn
    assert turn.tool_calls == [ToolCall(id="c1", name="grep", arguments={"pattern": "x"})]
    assert turn.finish_reason == "tool_calls"
    assert turn.truncated is False
    assert turn.usage is not None
    assert (turn.usage.input, turn.usage.output) == (12, 5)
    assert wire.closed == 1


# -- Property 2: randomized -------------------------------------------------------


def _maybe_break(rng, text):
    """Leave valid JSON, or (sometimes) make it really malformed."""
    roll = rng.random()
    if roll < 0.15:
        return text[: rng.randrange(1, len(text))]  # truncated: never valid JSON
    if roll < 0.2:
        return text + "}"  # trailing junk
    return text


def _indexed_deltas(rng):
    """1–4 calls, every delta carries its call's index; calls interleave arbitrarily."""
    count = rng.randint(1, 4)
    indices = rng.sample(range(count + 2), count)  # arbitrary, not necessarily 0..n-1
    queues = []
    for index in indices:
        call_id = f"call_{index}_{rng.randrange(10**6)}" if rng.random() < 0.9 else None
        repeat_id = rng.random() < 0.5
        repeat_name = rng.random() < 0.3
        name = rng.choice(_TOOL_NAMES)
        frags = _split(rng, _maybe_break(rng, _random_args_text(rng)))
        queues.append(
            [
                _delta(
                    index=index,
                    id=call_id if (i == 0 or repeat_id) else None,
                    name=name if (i == 0 or repeat_name) else None,
                    args=frag,
                )
                for i, frag in enumerate(frags)
            ]
        )
    deltas = []
    while any(queues):
        queue = rng.choice([q for q in queues if q])
        deltas.append(queue.pop(0))
    return deltas


def _single_call_deltas(rng):
    """Exactly one call; index randomly present or None; id randomly present."""
    index = rng.choice([None, 0, rng.randrange(1, 5)])
    call_id = f"call_{rng.randrange(10**6)}" if rng.random() < 0.7 else None
    repeat_id = call_id is not None and rng.random() < 0.5
    # A repeated name only makes sense alongside an id: an id-less stream that repeats the
    # name after a complete object is the separable multi-call shape (Property 1), not this.
    repeat_name = call_id is not None and rng.random() < 0.3
    name = rng.choice(_TOOL_NAMES)
    frags = _split(rng, _maybe_break(rng, _random_args_text(rng)))
    return [
        _delta(
            index=index,
            id=call_id if (i == 0 or repeat_id) else None,
            name=name if (i == 0 or repeat_name) else None,
            args=frag,
        )
        for i, frag in enumerate(frags)
    ]


@pytest.mark.parametrize("seed", range(60))
def test_random_indexed_streams_match_legacy(seed):
    rng = random.Random(5000 + seed)
    deltas = _indexed_deltas(rng)
    assert _final_turn(deltas).tool_calls == _legacy_tool_calls(deltas)


@pytest.mark.parametrize("seed", range(60))
def test_random_single_call_streams_match_legacy(seed):
    rng = random.Random(9000 + seed)
    deltas = _single_call_deltas(rng)
    legacy = _legacy_tool_calls(deltas)
    assert len(legacy) == 1
    assert _final_turn(deltas).tool_calls == legacy


# -- `_StreamToolCalls` boundary rules (unit) --------------------------------------
# **Validates: Requirements 2.1, 2.2, 2.4, 3.1, 3.2, 3.3**

from coworker.providers.openai_provider import _StreamToolCalls, _is_complete_json  # noqa: E402


def _accumulate(deltas):
    acc = _StreamToolCalls()
    for d in deltas:
        acc.add(d)
    return acc.calls()


def test_accum_new_id_starts_new_call():
    calls = _accumulate([
        _delta(id="c1", name="read_file", args='{"pa'),
        _delta(id="c2", name="grep", args='{"pattern": "x"}'),
    ])
    assert [(c.id, c.name) for c in calls] == [("c1", "read_file"), ("c2", "grep")]
    assert calls[0].arguments == {"_raw": '{"pa'}


def test_accum_same_id_continues_call():
    calls = _accumulate([
        _delta(id="c1", name="read_file", args='{"path": '),
        _delta(id="c1", args='"a.py"}'),
    ])
    assert calls == [ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})]


def test_accum_delta_without_id_continues_last_call():
    calls = _accumulate([
        _delta(id="c1", name="read_file", args='{"path": "a.py"}'),
        _delta(name="grep", args='{"pattern": "x"}'),  # no id, ids in play -> continue
    ])
    assert len(calls) == 1
    assert calls[0].id == "c1"


def test_accum_idless_stream_new_name_after_complete_json_starts_new_call():
    calls = _accumulate([
        _delta(name="load_skill", args='{"name": "pdf-translate-zh"}'),
        _delta(name="todo_write", args='{"todos": []}'),
    ])
    assert calls == [
        ToolCall(id="", name="load_skill", arguments={"name": "pdf-translate-zh"}),
        ToolCall(id="", name="todo_write", arguments={"todos": []}),
    ]


def test_accum_idless_same_name_with_blank_args_continues():
    calls = _accumulate([
        _delta(name="todo_write", args='{"todos": []}'),
        _delta(name="todo_write", args="  "),
    ])
    assert len(calls) == 1
    assert calls[0].arguments == {"todos": []}


def test_accum_empty_args_are_not_complete_json():
    assert not _is_complete_json("")
    assert not _is_complete_json("   ")
    assert _is_complete_json('{"a": 1}')
    # Previous call has a name but no args yet -> new name in an id-less stream continues.
    calls = _accumulate([
        _delta(name="read_file", args=""),
        _delta(name="grep", args='{"pattern": "x"}'),
    ])
    assert calls == [ToolCall(id="", name="grep", arguments={"pattern": "x"})]


def test_accum_mixed_index_outputs_indexed_first_then_arrival_order():
    calls = _accumulate([
        _delta(index=None, id="u1", name="grep", args='{"pattern": "x"}'),
        _delta(index=2, id="i2", name="bash", args='{"command": "ls"}'),
        _delta(index=None, id="u2", name="todo_write", args='{"todos": []}'),
        _delta(index=0, id="i0", name="read_file", args='{"path": "a.py"}'),
    ])
    assert [c.id for c in calls] == ["i0", "i2", "u1", "u2"]
